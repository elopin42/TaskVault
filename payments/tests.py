"""Offline tests for the payment modules (no network: `requests` is mocked everywhere)."""

from decimal import Decimal
from unittest.mock import Mock, patch

import requests
from django.test import SimpleTestCase, override_settings
from stellar_sdk import Keypair, Network, TransactionEnvelope
from stellar_sdk.operation import ChangeTrust, Payment

from payments import stellar, trustless_work as tw

CLIENT = Keypair.random().public_key  # the company wallet
FREELANCER = Keypair.random().public_key
PLATFORM = Keypair.random().public_key
USDC_ISSUER = "GBBD47IF6LWK7P7MDEVSCWR7DPUWV3NY3DTQEVFL4NAT4AQH3ZLLFLA5"
TESTNET = Network.TESTNET_NETWORK_PASSPHRASE
TW_URL = "https://dev.api.trustlesswork.com"
HORIZON = "https://horizon-testnet.stellar.org"


def _resp(status: int, payload=None, text: str = ""):
    """A minimal requests.Response stand-in."""
    r = Mock()
    r.status_code = status
    if payload is None:
        r.content = text.encode()
        r.text = text
        r.json = Mock(side_effect=ValueError("no json"))
    else:
        r.content = b"x"
        r.text = text
        r.json = Mock(return_value=payload)
    return r


def _horizon_account(with_usdc: bool = True, balance: str = "42.5", sequence: str = "123456789"):
    balances = [{"asset_type": "native", "balance": "9999.0000000"}]
    if with_usdc:
        balances.insert(0, {"asset_type": "credit_alphanum4", "asset_code": "USDC", "asset_issuer": USDC_ISSUER, "balance": balance})
    return {"id": CLIENT, "account_id": CLIENT, "sequence": sequence, "balances": balances}


# =============================== Trustless Work ===============================


@override_settings(
    TRUSTLESS_WORK_API_URL=TW_URL,
    TRUSTLESS_WORK_API_KEY="tw-test-key",
    STELLAR_ASSET_ISSUER=USDC_ISSUER,
    STELLAR_ASSET_CODE="USDC",
)
class TrustlessWorkClientTests(SimpleTestCase):
    def _post_ok(self, extra=None):
        payload = {"status": "SUCCESS", "unsignedTransaction": "AAAAAg=="}
        payload.update(extra or {})
        return patch("payments.trustless_work.requests.post", return_value=_resp(201, payload))

    def test_is_configured(self):
        self.assertTrue(tw.is_configured())
        with override_settings(TRUSTLESS_WORK_API_KEY=""):
            self.assertFalse(tw.is_configured())

    def test_not_configured_short_circuits_without_http(self):
        with override_settings(TRUSTLESS_WORK_API_KEY=""), patch("payments.trustless_work.requests.post") as post:
            env = tw.release_funds(contract_id="CABC", release_signer=CLIENT)
        post.assert_not_called()
        self.assertFalse(env["ok"])
        self.assertEqual(env["status"], 0)
        self.assertIn("clé API", env["error"])

    def test_deploy_body_and_headers(self):
        with self._post_ok() as post:
            env = tw.deploy_single_release(
                signer=CLIENT,
                engagement_id="lowbid-task-42",
                title="T" * 120,
                description="Task #42 of the yoga studio project",
                amount=Decimal("25"),
                approver=CLIENT,
                service_provider=FREELANCER,
                receiver=FREELANCER,
                release_signer=CLIENT,
                dispute_resolver=PLATFORM,
                platform_address=PLATFORM,
                platform_fee=Decimal("1"),
                milestone_description="Deliver the landing page",
            )
        self.assertTrue(env["ok"])
        self.assertEqual(env["status"], 201)
        self.assertEqual(env["data"]["unsignedTransaction"], "AAAAAg==")
        self.assertIsNone(env["error"])

        post.assert_called_once()
        args, kwargs = post.call_args
        self.assertEqual(args[0], f"{TW_URL}/deployer/single-release")
        self.assertEqual(kwargs["headers"]["x-api-key"], "tw-test-key")
        self.assertEqual(kwargs["headers"]["Content-Type"], "application/json")
        body = kwargs["json"]
        self.assertEqual(body["signer"], CLIENT)
        self.assertEqual(body["engagementId"], "lowbid-task-42")
        self.assertEqual(len(body["title"]), 100)  # clipped to the v1 limit
        self.assertEqual(
            body["roles"],
            {
                "approver": CLIENT,
                "serviceProvider": FREELANCER,
                "receiver": FREELANCER,
                "releaseSigner": CLIENT,
                "disputeResolver": PLATFORM,
                "platformAddress": PLATFORM,
            },
        )
        # JSON numbers in USDC units, never strings / stroops.
        self.assertIs(type(body["amount"]), int)
        self.assertEqual(body["amount"], 25)
        self.assertIs(type(body["platformFee"]), int)
        self.assertEqual(body["platformFee"], 1)
        self.assertEqual(body["milestones"], [{"description": "Deliver the landing page"}])
        self.assertEqual(body["trustline"], {"address": USDC_ISSUER, "symbol": "USDC"})

    def test_decimal_amount_becomes_float(self):
        with self._post_ok() as post:
            tw.fund_escrow(contract_id="CABC", signer=CLIENT, amount=Decimal("12.50"))
        args, kwargs = post.call_args
        self.assertEqual(args[0], f"{TW_URL}/escrow/single-release/fund-escrow")
        self.assertEqual(kwargs["json"], {"contractId": "CABC", "signer": CLIENT, "amount": 12.5})
        self.assertIs(type(kwargs["json"]["amount"]), float)

    def test_change_milestone_status_body(self):
        with self._post_ok() as post:
            tw.change_milestone_status(contract_id="CABC", evidence="https://lowbid.app/d/42", service_provider=FREELANCER)
        args, kwargs = post.call_args
        self.assertEqual(args[0], f"{TW_URL}/escrow/single-release/change-milestone-status")
        self.assertEqual(
            kwargs["json"],
            {
                "contractId": "CABC",
                "milestoneIndex": "0",
                "newStatus": "completed",
                "newEvidence": "https://lowbid.app/d/42",
                "serviceProvider": FREELANCER,
            },
        )
        self.assertIsInstance(kwargs["json"]["milestoneIndex"], str)

    def test_change_milestone_status_empty_evidence_is_sent_as_empty_string(self):
        with self._post_ok() as post:
            tw.change_milestone_status(contract_id="CABC", evidence=None, service_provider=FREELANCER)
        self.assertEqual(post.call_args.kwargs["json"]["newEvidence"], "")

    def test_approve_milestone_body(self):
        with self._post_ok() as post:
            tw.approve_milestone(contract_id="CABC", milestone_index=0, approver=CLIENT)
        args, kwargs = post.call_args
        self.assertEqual(args[0], f"{TW_URL}/escrow/single-release/approve-milestone")
        self.assertEqual(kwargs["json"], {"contractId": "CABC", "milestoneIndex": "0", "approver": CLIENT})

    def test_release_funds_body(self):
        with self._post_ok() as post:
            tw.release_funds(contract_id="CABC", release_signer=CLIENT)
        args, kwargs = post.call_args
        self.assertEqual(args[0], f"{TW_URL}/escrow/single-release/release-funds")
        self.assertEqual(kwargs["json"], {"contractId": "CABC", "releaseSigner": CLIENT})

    def test_send_transaction_returns_contract_id(self):
        payload = {"status": "SUCCESS", "message": "ok", "contractId": "CESCROW", "escrow": {"amount": 25}}
        with patch("payments.trustless_work.requests.post", return_value=_resp(200, payload)) as post:
            env = tw.send_transaction(signed_xdr="AAAAsigned")
        args, kwargs = post.call_args
        self.assertEqual(args[0], f"{TW_URL}/helper/send-transaction")
        self.assertEqual(kwargs["json"], {"signedXdr": "AAAAsigned"})
        self.assertTrue(env["ok"])
        self.assertEqual(env["data"]["contractId"], "CESCROW")

    def test_send_transaction_failed_status_is_not_ok(self):
        payload = {"status": "FAILED", "message": "tx_bad_auth"}
        with patch("payments.trustless_work.requests.post", return_value=_resp(200, payload)):
            env = tw.send_transaction(signed_xdr="AAAAsigned")
        self.assertFalse(env["ok"])
        self.assertEqual(env["status"], 200)
        self.assertEqual(env["error"], "tx_bad_auth")

    def test_set_trustline_body(self):
        with self._post_ok() as post:
            tw.set_trustline(address=FREELANCER)
        args, kwargs = post.call_args
        self.assertEqual(args[0], f"{TW_URL}/helper/set-trustline")
        self.assertEqual(kwargs["json"], {"address": FREELANCER, "assetAddress": USDC_ISSUER})

    def test_get_escrow_uses_get_with_params(self):
        payload = {"contractId": "CABC", "platformFee": 1, "balance": 25, "flags": {"released": False}}
        with patch("payments.trustless_work.requests.get", return_value=_resp(200, payload)) as get:
            env = tw.get_escrow(contract_id="CABC", signer=CLIENT, validate_on_chain=True)
        args, kwargs = get.call_args
        self.assertEqual(args[0], f"{TW_URL}/escrow/single-release/get-escrow")
        self.assertEqual(kwargs["params"], {"contractId": "CABC", "signer": CLIENT, "validateOnChain": "true"})
        self.assertEqual(kwargs["headers"]["x-api-key"], "tw-test-key")
        self.assertTrue(env["ok"])
        self.assertEqual(env["data"]["platformFee"], 1)

    def test_transport_error_does_not_raise(self):
        with patch("payments.trustless_work.requests.post", side_effect=requests.ConnectionError("boom")):
            with self.assertLogs("payments.trustless_work", level="WARNING") as logs:
                env = tw.fund_escrow(contract_id="CABC", signer=CLIENT, amount=Decimal("1"))
        self.assertEqual(env, {"ok": False, "status": 0, "data": {}, "error": tw.ERR_UNREACHABLE})
        self.assertIn("fund-escrow", logs.output[0])
        self.assertNotIn("tw-test-key", "".join(logs.output))

    def test_timeout_is_a_transport_error(self):
        with patch("payments.trustless_work.requests.get", side_effect=requests.Timeout()):
            env = tw.get_escrow(contract_id="CABC")
        self.assertFalse(env["ok"])
        self.assertEqual(env["status"], 0)

    def test_4xx_returns_message(self):
        payload = {"statusCode": 400, "message": ["amount must be a positive number"], "error": "Bad Request"}
        with patch("payments.trustless_work.requests.post", return_value=_resp(400, payload)):
            env = tw.fund_escrow(contract_id="CABC", signer=CLIENT, amount=Decimal("1"))
        self.assertFalse(env["ok"])
        self.assertEqual(env["status"], 400)
        self.assertEqual(env["error"], "amount must be a positive number")
        self.assertEqual(env["data"]["statusCode"], 400)

    def test_401_without_message(self):
        with patch("payments.trustless_work.requests.post", return_value=_resp(401, {})):
            env = tw.release_funds(contract_id="CABC", release_signer=CLIENT)
        self.assertFalse(env["ok"])
        self.assertEqual(env["error"], "HTTP 401")

    def test_non_json_body(self):
        with patch("payments.trustless_work.requests.post", return_value=_resp(502, None, text="<html>bad gateway</html>")):
            env = tw.release_funds(contract_id="CABC", release_signer=CLIENT)
        self.assertFalse(env["ok"])
        self.assertEqual(env["status"], 502)
        self.assertIn("bad gateway", env["data"]["raw"])


# =============================== stellar.py ===============================


@override_settings(
    STELLAR_NETWORK="testnet",
    STELLAR_NETWORK_PASSPHRASE=TESTNET,
    STELLAR_HORIZON_URL=HORIZON,
    STELLAR_ASSET_ISSUER=USDC_ISSUER,
    STELLAR_ASSET_CODE="USDC",
)
class StellarBuildersTests(SimpleTestCase):
    def test_asset_from_settings(self):
        asset = stellar.asset()
        self.assertEqual((asset.code, asset.issuer), ("USDC", USDC_ISSUER))
        self.assertFalse(stellar.is_native())
        self.assertEqual(stellar.asset_code(), "USDC")
        with override_settings(STELLAR_ASSET_CODE="eurc", STELLAR_ASSET_ISSUER=PLATFORM):
            self.assertEqual((stellar.asset().code, stellar.asset().issuer), ("EURC", PLATFORM))

    def test_native_asset(self):
        with override_settings(STELLAR_ASSET_CODE="XLM", STELLAR_ASSET_ISSUER=""):
            self.assertTrue(stellar.is_native())
            self.assertTrue(stellar.asset().is_native())
            xdr = stellar.build_payment_xdr(source=CLIENT, destination=FREELANCER, amount=Decimal("2"), sequence=5)
            op = TransactionEnvelope.from_xdr(xdr, TESTNET).transaction.operations[0]
            self.assertTrue(op.asset.is_native())
            info = stellar.parse_payment_xdr(xdr)
            self.assertEqual((info["asset_code"], info["asset_issuer"]), ("XLM", None))
            with self.assertRaises(stellar.StellarError):
                stellar.build_change_trust_xdr(source=CLIENT, sequence=1)
            with patch("payments.stellar.requests.get") as get:
                self.assertTrue(stellar.has_trustline(CLIENT))  # no trustline needed, no Horizon call
            get.assert_not_called()
            with patch("payments.stellar.requests.get", return_value=_resp(200, _horizon_account(with_usdc=False))):
                self.assertEqual(stellar.asset_balance(CLIENT), Decimal("9999"))
            self.assertEqual(stellar.explain_result_codes({"operations": ["op_underfunded"]}), "Solde XLM insuffisant.")

    def test_result_code_messages_carry_the_asset_code(self):
        self.assertEqual(stellar.explain_result_codes({"operations": ["op_no_trust"]}), "Le destinataire n’a pas de trustline USDC.")
        with override_settings(STELLAR_ASSET_CODE="EURC", STELLAR_ASSET_ISSUER=PLATFORM):
            self.assertEqual(stellar.explain_result_codes({"operations": ["op_no_trust"]}), "Le destinataire n’a pas de trustline EURC.")

    def test_build_payment_xdr_offline_roundtrip(self):
        with patch("payments.stellar.requests.get") as get:
            xdr = stellar.build_payment_xdr(
                source=CLIENT, destination=FREELANCER, amount=Decimal("12.50"), memo="lowbid:42", sequence=1000
            )
        get.assert_not_called()  # sequence injected → no Horizon round trip
        env = TransactionEnvelope.from_xdr(xdr, TESTNET)
        tx = env.transaction
        self.assertEqual(tx.source.account_id, CLIENT)
        self.assertEqual(tx.sequence, 1001)
        self.assertEqual(tx.fee, 100)
        self.assertEqual(len(tx.operations), 1)
        op = tx.operations[0]
        self.assertIsInstance(op, Payment)
        self.assertEqual(op.destination.account_id, FREELANCER)
        self.assertEqual(Decimal(op.amount), Decimal("12.5"))
        self.assertEqual((op.asset.code, op.asset.issuer), ("USDC", USDC_ISSUER))
        self.assertEqual(tx.memo.memo_text, b"lowbid:42")
        self.assertIsNotNone(tx.preconditions.time_bounds)
        self.assertGreater(tx.preconditions.time_bounds.max_time, 0)
        self.assertEqual(len(env.signatures), 0)
        # Wrong network → the XDR does not verify under another passphrase hash, but still parses;
        # the hash differs, which is what Freighter/Horizon check.
        self.assertNotEqual(env.hash_hex(), TransactionEnvelope.from_xdr(xdr, Network.PUBLIC_NETWORK_PASSPHRASE).hash_hex())

    def test_build_payment_xdr_without_memo(self):
        xdr = stellar.build_payment_xdr(source=CLIENT, destination=FREELANCER, amount=Decimal("1"), sequence=5)
        tx = TransactionEnvelope.from_xdr(xdr, TESTNET).transaction
        self.assertEqual(tx.memo.to_xdr_object().type.name, "MEMO_NONE")

    def test_memo_is_cut_to_28_bytes(self):
        xdr = stellar.build_payment_xdr(source=CLIENT, destination=FREELANCER, amount=Decimal("1"), memo="é" * 30, sequence=5)
        tx = TransactionEnvelope.from_xdr(xdr, TESTNET).transaction
        self.assertLessEqual(len(tx.memo.memo_text), 28)
        self.assertEqual(tx.memo.memo_text.decode("utf-8"), "é" * 14)

    def test_build_payment_xdr_rejects_bad_amounts(self):
        for bad in (Decimal("0"), Decimal("-1"), Decimal("1.12345678"), "abc"):
            with self.assertRaises(stellar.StellarError):
                stellar.build_payment_xdr(source=CLIENT, destination=FREELANCER, amount=bad, sequence=5)

    def test_build_payment_xdr_loads_sequence_and_fee_from_horizon(self):
        def fake_get(url, **kwargs):
            if url.endswith(f"/accounts/{CLIENT}"):
                return _resp(200, _horizon_account(sequence="777"))
            if url.endswith("/fee_stats"):
                return _resp(200, {"last_ledger_base_fee": "150"})
            raise AssertionError(url)

        with patch("payments.stellar.requests.get", side_effect=fake_get):
            xdr = stellar.build_payment_xdr(source=CLIENT, destination=FREELANCER, amount=Decimal("2"))
        tx = TransactionEnvelope.from_xdr(xdr, TESTNET).transaction
        self.assertEqual(tx.sequence, 778)
        self.assertEqual(tx.fee, 150)

    def test_build_payment_xdr_unfunded_source(self):
        with patch("payments.stellar.requests.get", return_value=_resp(404, {"status": 404})):
            with self.assertRaises(stellar.StellarError) as ctx:
                stellar.build_payment_xdr(source=CLIENT, destination=FREELANCER, amount=Decimal("2"))
        self.assertIn("friendbot", str(ctx.exception))

    def test_build_payment_xdr_horizon_down_is_not_account_not_found(self):
        """A proxy 403 / 5xx / transport error must say "Horizon injoignable", not "financez-le"."""
        for failing in (
            {"return_value": _resp(403, {"status": 403})},
            {"return_value": _resp(503, {})},
            {"side_effect": requests.ConnectionError("down")},
        ):
            with patch("payments.stellar.requests.get", **failing):
                with self.assertRaises(stellar.StellarError) as ctx:
                    stellar.build_payment_xdr(source=CLIENT, destination=FREELANCER, amount=Decimal("2"))
            self.assertEqual(str(ctx.exception), stellar.ERR_HORIZON_UNREACHABLE)

    def test_build_change_trust_xdr_offline(self):
        xdr = stellar.build_change_trust_xdr(source=FREELANCER, sequence=42)
        tx = TransactionEnvelope.from_xdr(xdr, TESTNET).transaction
        self.assertEqual(tx.source.account_id, FREELANCER)
        self.assertEqual(len(tx.operations), 1)
        op = tx.operations[0]
        self.assertIsInstance(op, ChangeTrust)
        self.assertEqual((op.asset.code, op.asset.issuer), ("USDC", USDC_ISSUER))
        self.assertEqual(Decimal(op.limit), Decimal("922337203685.4775807"))

    def test_parse_payment_xdr(self):
        xdr = stellar.build_payment_xdr(source=CLIENT, destination=FREELANCER, amount=Decimal("3.25"), memo="lowbid:7", sequence=9)
        info = stellar.parse_payment_xdr(xdr)
        self.assertEqual(info["op_type"], "payment")
        self.assertEqual(info["source"], CLIENT)
        self.assertEqual(info["destination"], FREELANCER)
        self.assertEqual(info["amount"], Decimal("3.25"))
        self.assertEqual(info["asset_issuer"], USDC_ISSUER)
        self.assertEqual(info["memo"], "lowbid:7")
        self.assertEqual(len(info["hash"]), 64)
        self.assertEqual(stellar.parse_payment_xdr(stellar.build_change_trust_xdr(source=CLIENT, sequence=1))["op_type"], "change_trust")
        self.assertIsNone(stellar.parse_payment_xdr("not-xdr"))


@override_settings(
    STELLAR_NETWORK="testnet",
    STELLAR_NETWORK_PASSPHRASE=TESTNET,
    STELLAR_HORIZON_URL=HORIZON,
    STELLAR_ASSET_ISSUER=USDC_ISSUER,
    STELLAR_ASSET_CODE="USDC",
)
class StellarSubmitTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        kp = Keypair.random()
        with override_settings(STELLAR_NETWORK_PASSPHRASE=TESTNET, STELLAR_ASSET_ISSUER=USDC_ISSUER, STELLAR_ASSET_CODE="USDC"):
            xdr = stellar.build_payment_xdr(source=kp.public_key, destination=FREELANCER, amount=Decimal("1"), sequence=1)
        env = TransactionEnvelope.from_xdr(xdr, TESTNET)
        env.sign(kp)
        cls.signed_xdr = env.to_xdr()
        cls.expected_hash = env.hash_hex()

    def test_submit_success(self):
        payload = {"hash": self.expected_hash, "ledger": 12345, "successful": True}
        with patch("payments.stellar.requests.post", return_value=_resp(200, payload)) as post:
            env = stellar.submit_xdr(self.signed_xdr)
        args, kwargs = post.call_args
        self.assertEqual(args[0], f"{HORIZON}/transactions")
        self.assertEqual(kwargs["data"], {"tx": self.signed_xdr})
        self.assertTrue(env["ok"])
        self.assertEqual(env["hash"], self.expected_hash)
        self.assertEqual(env["data"]["ledger"], 12345)
        self.assertIsNone(env["error"])

    def test_submit_maps_op_no_trust(self):
        payload = {
            "type": "https://stellar.org/horizon-errors/transaction_failed",
            "title": "Transaction Failed",
            "status": 400,
            "extras": {"result_codes": {"transaction": "tx_failed", "operations": ["op_no_trust"]}},
        }
        with patch("payments.stellar.requests.post", return_value=_resp(400, payload)):
            env = stellar.submit_xdr(self.signed_xdr)
        self.assertFalse(env["ok"])
        self.assertEqual(env["status"], 400)
        self.assertEqual(env["error"], "Le destinataire n’a pas de trustline USDC.")
        self.assertEqual(env["hash"], self.expected_hash)  # computed locally even on failure

    def test_submit_maps_tx_codes(self):
        cases = {
            "op_underfunded": "Solde USDC insuffisant.",
            "op_no_destination": "Le compte destinataire n’existe pas encore sur le réseau (financez-le via friendbot).",
        }
        for code, message in cases.items():
            payload = {"extras": {"result_codes": {"transaction": "tx_failed", "operations": [code]}}}
            with patch("payments.stellar.requests.post", return_value=_resp(400, payload)):
                self.assertEqual(stellar.submit_xdr(self.signed_xdr)["error"], message)
        payload = {"extras": {"result_codes": {"transaction": "tx_bad_seq"}}}
        with patch("payments.stellar.requests.post", return_value=_resp(400, payload)):
            self.assertEqual(stellar.submit_xdr(self.signed_xdr)["error"], "Réessayez (numéro de séquence dépassé).")
        payload = {"extras": {"result_codes": {"transaction": "tx_bad_auth"}}}
        with patch("payments.stellar.requests.post", return_value=_resp(400, payload)):
            self.assertIn("autre adresse", stellar.submit_xdr(self.signed_xdr)["error"])
        payload = {"extras": {"result_codes": {"transaction": "tx_weird"}}}
        with patch("payments.stellar.requests.post", return_value=_resp(400, payload)):
            self.assertEqual(stellar.submit_xdr(self.signed_xdr)["error"], "Transaction rejetée (tx_weird).")

    def test_submit_timeout_504(self):
        with patch("payments.stellar.requests.post", return_value=_resp(504, {"status": 504, "title": "Timeout"})):
            env = stellar.submit_xdr(self.signed_xdr)
        self.assertFalse(env["ok"])
        self.assertEqual(env["status"], 504)
        self.assertEqual(env["error"], stellar.ERR_TIMEOUT)
        self.assertEqual(env["hash"], self.expected_hash)

    def test_submit_transport_error(self):
        with patch("payments.stellar.requests.post", side_effect=requests.ConnectionError("down")):
            env = stellar.submit_xdr(self.signed_xdr)
        self.assertEqual(env["ok"], False)
        self.assertEqual(env["status"], 0)
        self.assertEqual(env["error"], stellar.ERR_HORIZON_UNREACHABLE)

    def test_submit_bad_xdr(self):
        with patch("payments.stellar.requests.post") as post:
            env = stellar.submit_xdr("not an xdr")
        post.assert_not_called()
        self.assertFalse(env["ok"])
        self.assertEqual(env["error"], stellar.ERR_BAD_XDR)

    def test_explain_result_codes(self):
        self.assertEqual(stellar.explain_result_codes(None), "La transaction a été rejetée par le réseau.")
        self.assertEqual(
            stellar.explain_result_codes({"transaction": "tx_failed", "operations": ["op_success", "op_line_full"]}),
            "La trustline du destinataire est pleine.",
        )
        self.assertEqual(stellar.explain_result_codes({"operations": ["op_xyz"]}), "Opération rejetée (op_xyz).")


@override_settings(
    STELLAR_NETWORK="testnet",
    STELLAR_HORIZON_URL=HORIZON,
    STELLAR_ASSET_ISSUER=USDC_ISSUER,
    STELLAR_ASSET_CODE="USDC",
)
class StellarHorizonReadTests(SimpleTestCase):
    def test_has_trustline(self):
        with patch("payments.stellar.requests.get", return_value=_resp(200, _horizon_account(with_usdc=True))) as get:
            self.assertTrue(stellar.has_trustline(CLIENT))
        self.assertEqual(get.call_args.args[0], f"{HORIZON}/accounts/{CLIENT}")
        with patch("payments.stellar.requests.get", return_value=_resp(200, _horizon_account(with_usdc=False))):
            self.assertFalse(stellar.has_trustline(CLIENT))
        with patch("payments.stellar.requests.get", return_value=_resp(404, {"status": 404})):
            self.assertFalse(stellar.has_trustline(CLIENT))
        with patch("payments.stellar.requests.get", side_effect=requests.ConnectionError()):
            self.assertIsNone(stellar.has_trustline(CLIENT))
        with patch("payments.stellar.requests.get", return_value=_resp(503, {})):
            self.assertIsNone(stellar.has_trustline(CLIENT))

    def test_other_issuer_does_not_count(self):
        acc = _horizon_account(with_usdc=False)
        acc["balances"].insert(0, {"asset_type": "credit_alphanum4", "asset_code": "USDC", "asset_issuer": PLATFORM, "balance": "5"})
        with patch("payments.stellar.requests.get", return_value=_resp(200, acc)):
            self.assertFalse(stellar.has_trustline(CLIENT))
            self.assertEqual(stellar.asset_balance(CLIENT), Decimal("0"))

    def test_asset_balance(self):
        with patch("payments.stellar.requests.get", return_value=_resp(200, _horizon_account(balance="42.5000000"))):
            self.assertEqual(stellar.asset_balance(CLIENT), Decimal("42.5"))
        with patch("payments.stellar.requests.get", return_value=_resp(200, _horizon_account(with_usdc=False))):
            self.assertEqual(stellar.asset_balance(CLIENT), Decimal("0"))
        with patch("payments.stellar.requests.get", return_value=_resp(404, {})):
            self.assertEqual(stellar.asset_balance(CLIENT), Decimal("0"))
        with patch("payments.stellar.requests.get", side_effect=requests.Timeout()):
            with self.assertLogs("payments.stellar", level="WARNING"):
                self.assertIsNone(stellar.asset_balance(CLIENT))

    def test_load_sequence_and_base_fee(self):
        with patch("payments.stellar.requests.get", return_value=_resp(200, _horizon_account(sequence="99"))):
            self.assertEqual(stellar.load_sequence(CLIENT), 99)
        with patch("payments.stellar.requests.get", return_value=_resp(404, {})):
            self.assertIsNone(stellar.load_sequence(CLIENT))
        with patch("payments.stellar.requests.get", return_value=_resp(200, {"last_ledger_base_fee": "100"})):
            self.assertEqual(stellar.horizon_base_fee(), 100)
        with patch("payments.stellar.requests.get", side_effect=requests.ConnectionError()):
            self.assertEqual(stellar.horizon_base_fee(), 100)


class PaymentModeAndExplorerTests(SimpleTestCase):
    def test_payment_mode_explicit(self):
        with override_settings(LOWBID_PAYMENT_MODE="direct", TRUSTLESS_WORK_API_KEY="k"):
            self.assertEqual(stellar.payment_mode(), "direct")
        with override_settings(LOWBID_PAYMENT_MODE="escrow", TRUSTLESS_WORK_API_KEY=""):
            self.assertEqual(stellar.payment_mode(), "escrow")
        with override_settings(LOWBID_PAYMENT_MODE="ESCROW ", TRUSTLESS_WORK_API_KEY=""):
            self.assertEqual(stellar.payment_mode(), "escrow")

    def test_payment_mode_auto(self):
        with override_settings(LOWBID_PAYMENT_MODE="", TRUSTLESS_WORK_API_KEY="k"):
            self.assertEqual(stellar.payment_mode(), "escrow")
        with override_settings(LOWBID_PAYMENT_MODE="", TRUSTLESS_WORK_API_KEY=""):
            self.assertEqual(stellar.payment_mode(), "direct")
        with override_settings(LOWBID_PAYMENT_MODE="bogus", TRUSTLESS_WORK_API_KEY=""):
            self.assertEqual(stellar.payment_mode(), "direct")

    def test_native_asset_refuses_escrow_mode_with_a_warning(self):
        stellar._native_fallback_warned = False  # the fallback is logged once per process
        with override_settings(LOWBID_PAYMENT_MODE="escrow", TRUSTLESS_WORK_API_KEY="k", STELLAR_ASSET_CODE="XLM", STELLAR_ASSET_ISSUER=""):
            with self.assertLogs("payments.stellar", level="WARNING") as logs:
                self.assertEqual(stellar.payment_mode(), "direct")
            with self.assertNoLogs("payments.stellar", level="WARNING"):  # second call: silent
                self.assertEqual(stellar.payment_mode(), "direct")
        self.assertIn("native", logs.output[0])
        with override_settings(LOWBID_PAYMENT_MODE="direct", STELLAR_ASSET_CODE="XLM", STELLAR_ASSET_ISSUER=""):
            self.assertEqual(stellar.payment_mode(), "direct")

    def test_legacy_usdc_settings_are_the_default(self):
        from django.conf import settings

        self.assertEqual(settings.STELLAR_ASSET_CODE, settings.STELLAR_USDC_CODE)
        self.assertEqual(settings.STELLAR_ASSET_ISSUER, settings.STELLAR_USDC_ISSUER)

    def test_explorer_urls(self):
        with override_settings(STELLAR_NETWORK="testnet"):
            self.assertEqual(stellar.explorer_tx_url("abc"), "https://stellar.expert/explorer/testnet/tx/abc")
            self.assertEqual(stellar.explorer_account_url(CLIENT), f"https://stellar.expert/explorer/testnet/account/{CLIENT}")
            self.assertEqual(stellar.explorer_contract_url("CXYZ"), "https://stellar.expert/explorer/testnet/contract/CXYZ")
        with override_settings(STELLAR_NETWORK="public"):
            self.assertEqual(stellar.explorer_tx_url("abc"), "https://stellar.expert/explorer/public/tx/abc")

    def test_settings_defaults(self):
        from django.conf import settings

        self.assertIn(settings.LOWBID_PAYMENT_MODE, ("", "escrow", "direct"))
        self.assertEqual(settings.LOWBID_PLATFORM_FEE, Decimal("1"))
        self.assertIsInstance(settings.LOWBID_PLATFORM_ADDRESS, str)
