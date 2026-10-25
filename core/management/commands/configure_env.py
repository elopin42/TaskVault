"""Interactive `.env` wizard, run by `make` (target `env`) so every key the site needs gets a value.

  1. Creates `.env` from `.env.example` if missing, and appends the keys of `.env.example` that an
     older `.env` lacks (comments and existing values are kept untouched).
  2. Replaces the placeholder DJANGO_SECRET_KEY with a random one.
  3. Asks for the keys that make the site fully work: the Trustless Work API key, the payment mode
     and, in escrow mode, the platform key, the deposit resolver key, the guarantee fund wallet, the
     arbiter; then the optional GitHub token and the demo wallets. Any Stellar key can be GENERATED
     (type `g`), and generated testnet accounts can be funded by Friendbot + given the asset trustline.

The full wizard runs once (stamp: data/.env-configured); later runs only ask for keys the chosen mode
still misses. `make configure` (= `--all`) asks everything again; `--no-input` (or a non-TTY stdin,
or `make NO_PROMPT=1`) never asks. Secrets are typed hidden and never echoed back.

    python manage.py configure_env [--all] [--no-input]
"""

import getpass
import logging
import secrets
import sys
from pathlib import Path

import requests
from django.conf import settings
from django.core.management.base import BaseCommand
from stellar_sdk import Asset, Keypair, Network, Server, StrKey, TransactionBuilder

logger = logging.getLogger(__name__)

PLACEHOLDER_SECRET_KEY = "change-me-in-production"
FRIENDBOT_URL = "https://friendbot.stellar.org"
DEMO_KEYS = [
    ("LOWBID_DEMO_CLIENT", "Demo company wallet (your Freighter account)"),
    ("LOWBID_DEMO_FREELANCE1", "Demo freelancer A wallet"),
    ("LOWBID_DEMO_FREELANCE2", "Demo freelancer B wallet"),
    ("LOWBID_DEMO_FREELANCE3", "Demo freelancer C wallet"),
    ("LOWBID_DEMO_ARBITER", "Demo arbiter wallet (empty = LOWBID_DISPUTE_RESOLVER)"),
]


class EnvFile:
    """`.env` lines kept verbatim; `set` rewrites `KEY=…` (or uncomments `# KEY=…`) in place, else appends."""

    def __init__(self, path: Path):
        self.path = path
        self.lines = path.read_text().splitlines() if path.exists() else []

    @staticmethod
    def _key(line: str, commented: bool = False) -> str | None:
        text = line.strip()
        if commented:
            if not text.startswith("#"):
                return None
            text = text.lstrip("#").strip()
        elif text.startswith("#"):
            return None
        if "=" not in text:
            return None
        key = text.split("=", 1)[0].strip()
        return key if key.isidentifier() and key.isupper() else None

    def keys(self) -> set[str]:
        return {k for k in (self._key(line) for line in self.lines) if k}

    def get(self, key: str) -> str:
        for line in self.lines:
            if self._key(line) == key:
                return line.split("=", 1)[1].strip().strip('"').strip("'")
        return ""

    def set(self, key: str, value: str) -> None:
        new = f"{key}={value}"
        for i, line in enumerate(self.lines):
            if self._key(line) == key:
                self.lines[i] = new
                return
        for i, line in enumerate(self.lines):
            if self._key(line, commented=True) == key:
                self.lines[i] = new
                return
        self.lines.append(new)

    def save(self) -> None:
        self.path.write_text("\n".join(self.lines) + "\n")
        self.path.chmod(0o600)


def _is_secret(value: str) -> bool:
    try:
        return StrKey.is_valid_ed25519_secret_seed(value)
    except Exception:  # stellar_sdk raises on malformed input instead of returning False
        return False


def _is_address(value: str) -> bool:
    try:
        return StrKey.is_valid_ed25519_public_key(value)
    except Exception:
        return False


def _mask(value: str) -> str:
    return f"{value[:2]}…{value[-4:]}" if len(value) > 8 else "set"


class Command(BaseCommand):
    help = "Ask for the .env keys the site needs (Trustless Work, Stellar keys, deposit, demo wallets)."

    def add_arguments(self, parser):
        parser.add_argument("--all", action="store_true", help="Ask every question again, even for keys already set.")
        parser.add_argument("--no-input", action="store_true", help="Never prompt (sync keys and the secret key only).")

    # --- prompts -------------------------------------------------------------

    def _ask(self, label: str, current: str = "", *, secret: bool = False, default: str = "") -> str:
        shown = (_mask(current) if secret else current) if current else (default or "empty")
        prompt = f"  {label} [{shown}]: "
        try:
            answer = (getpass.getpass(prompt) if secret else input(prompt)).strip()
        except EOFError:
            answer = ""
        return answer or current or default

    def _yes(self, label: str, default: bool = True) -> bool:
        hint = "Y/n" if default else "y/N"
        try:
            answer = input(f"  {label} [{hint}]: ").strip().lower()
        except EOFError:
            answer = ""
        return default if not answer else answer.startswith(("y", "o"))

    def _note(self, text: str) -> None:
        self.stdout.write(self.style.HTTP_INFO(text))

    def _section(self, title: str) -> None:
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING(f"== {title}"))

    def _stellar_key(self, env: EnvFile, key: str, label: str, *, kind: str) -> str:
        """Ask for a secret (S…) or an address (G…); `g` generates a fresh keypair."""
        current = env.get(key)
        while True:
            value = self._ask(f"{label} ('g' = generate)", current, secret=(kind == "secret"))
            if value.lower() == "g":
                pair = Keypair.random()
                self._generated.append(pair)
                if kind == "secret":
                    self.stdout.write(f"    generated, public key {pair.public_key}")
                    return pair.secret
                self.stdout.write(f"    generated {pair.public_key}")
                self.stdout.write(self.style.WARNING(f"    its secret (save it, shown once): {pair.secret}"))
                return pair.public_key
            if not value or (kind == "secret" and _is_secret(value)) or (kind == "address" and _is_address(value)):
                return value
            self.stdout.write(self.style.ERROR(f"    not a valid Stellar {'secret key (S…)' if kind == 'secret' else 'address (G…)'}"))

    # --- testnet funding -----------------------------------------------------

    def _fund(self, env: EnvFile, pairs: list[Keypair], trust: set[str]) -> None:
        """Friendbot (XLM) for each new account, then a trustline to the payment asset where it is needed."""
        horizon_url = env.get("STELLAR_HORIZON_URL") or settings.STELLAR_HORIZON_URL
        code = (env.get("STELLAR_ASSET_CODE") or "USDC").upper()
        issuer = env.get("STELLAR_ASSET_ISSUER")
        server = Server(horizon_url)
        for pair in pairs:
            address = pair.public_key
            try:
                response = requests.get(FRIENDBOT_URL, params={"addr": address}, timeout=30)
                ok = response.status_code == 200 or "already" in response.text.lower()
                self.stdout.write(f"    friendbot {address[:6]}…: {'ok' if ok else response.status_code}")
                if not (ok and address in trust and issuer):
                    continue
                account = server.load_account(address)
                tx = (
                    TransactionBuilder(account, Network.TESTNET_NETWORK_PASSPHRASE, base_fee=1000)
                    .append_change_trust_op(Asset(code, issuer))
                    .set_timeout(60)
                    .build()
                )
                tx.sign(pair)
                server.submit_transaction(tx)
                self.stdout.write(f"    trustline {code} on {address[:6]}…: ok")
            except Exception:
                logger.exception("configure_env: testnet funding failed address=%s", address)
                self.stdout.write(self.style.ERROR(f"    funding {address[:6]}… failed (see the log), fund it by hand"))

    # --- main ----------------------------------------------------------------

    def handle(self, *args, **options):
        base = Path(settings.BASE_DIR)
        path, example = base / ".env", EnvFile(base / ".env.example")
        stamp = base / "data" / ".env-configured"
        created = not path.exists()
        env = EnvFile(path)
        if created:
            env.lines = list(example.lines)
            self.stdout.write("created .env from .env.example")
        missing = sorted(example.keys() - env.keys())
        if missing:
            env.lines += ["", "# --- added by `manage.py configure_env` from .env.example ---"]
            for key in missing:
                env.lines.append(f"{key}={example.get(key)}")
            self.stdout.write(f"added to .env: {', '.join(missing)}")
        if env.get("DJANGO_SECRET_KEY") in ("", PLACEHOLDER_SECRET_KEY):
            env.set("DJANGO_SECRET_KEY", secrets.token_urlsafe(50))
            self.stdout.write("generated DJANGO_SECRET_KEY")

        interactive = not options["no_input"] and sys.stdin.isatty()
        full = options["all"] or not stamp.exists()
        if interactive:
            self._generated: list[Keypair] = []
            self._wizard(env, full)
        env.save()
        if interactive:
            stamp.parent.mkdir(exist_ok=True)
            stamp.touch()
            if self._generated and (env.get("STELLAR_NETWORK") or "testnet") == "testnet":
                trust = {a for a in (env.get("LOWBID_PLATFORM_ADDRESS"), env.get("LOWBID_GUARANTEE_FUND_ADDRESS")) if a}
                if self._yes(f"Fund the {len(self._generated)} generated testnet account(s) (Friendbot + trustline)?"):
                    self._fund(env, self._generated, trust)
            self.stdout.write(self.style.SUCCESS(".env saved — `make configure` asks everything again."))

    def _wizard(self, env: EnvFile, full: bool) -> None:
        ask = lambda key: full or not env.get(key)  # asked once, then only while empty
        if full:
            self.stdout.write("")
            self.stdout.write(self.style.MIGRATE_HEADING("TaskVault setup — press Enter to keep the value in brackets."))

        if full:
            self._section("Payments")
            self._note("  Trustless Work API key: https://dapp.trustlesswork.com (testnet). Empty = direct USDC payments.")
            env.set("TRUSTLESS_WORK_API_KEY", self._ask("TRUSTLESS_WORK_API_KEY", env.get("TRUSTLESS_WORK_API_KEY"), secret=True))
            while True:
                mode = self._ask("Payment mode: auto | escrow | direct", env.get("LOWBID_PAYMENT_MODE"), default="auto")
                if mode in ("auto", "escrow", "direct"):
                    break
            env.set("LOWBID_PAYMENT_MODE", "" if mode == "auto" else mode)

        mode = env.get("LOWBID_PAYMENT_MODE")
        native = (env.get("STELLAR_ASSET_CODE") or "").upper() == "XLM" and not env.get("STELLAR_ASSET_ISSUER")
        escrow = not native and mode != "direct" and (mode == "escrow" or bool(env.get("TRUSTLESS_WORK_API_KEY")))
        if not escrow:
            if full:
                self._note("  Direct mode: no escrow key needed.")
        else:
            if mode == "escrow" and not env.get("TRUSTLESS_WORK_API_KEY"):
                self._section("Payments")
                env.set("TRUSTLESS_WORK_API_KEY", self._ask("TRUSTLESS_WORK_API_KEY (required in escrow mode)", secret=True))
            if ask("LOWBID_PLATFORM_SECRET") or ask("LOWBID_PLATFORM_ADDRESS"):
                self._section("Platform wallet (escrow fee receiver, signs the deposit refunds)")
                secret = self._stellar_key(env, "LOWBID_PLATFORM_SECRET", "LOWBID_PLATFORM_SECRET (S…, empty = no deposits)", kind="secret")
                env.set("LOWBID_PLATFORM_SECRET", secret)
                if secret:
                    env.set("LOWBID_PLATFORM_ADDRESS", Keypair.from_secret(secret).public_key)
                    self.stdout.write(f"    LOWBID_PLATFORM_ADDRESS = {env.get('LOWBID_PLATFORM_ADDRESS')}")
                else:
                    env.set("LOWBID_PLATFORM_ADDRESS", self._stellar_key(env, "LOWBID_PLATFORM_ADDRESS", "LOWBID_PLATFORM_ADDRESS (G…)", kind="address"))
            if full:
                self._section("Disputes")
                self._note("  The arbiter wallet signs resolve-dispute and is the only one that opens /litiges/.")
                env.set("LOWBID_DISPUTE_RESOLVER", self._stellar_key(env, "LOWBID_DISPUTE_RESOLVER", "LOWBID_DISPUTE_RESOLVER (G…, empty = platform wallet)", kind="address"))
                self._section("Publication deposit")
                enabled = self._yes("Enable the publication deposit?", env.get("LOWBID_DEPOSIT_ENABLED") != "0")
                env.set("LOWBID_DEPOSIT_ENABLED", "1" if enabled else "0")
            if env.get("LOWBID_DEPOSIT_ENABLED") != "0" and env.get("LOWBID_PLATFORM_SECRET"):
                if ask("LOWBID_DEPOSIT_RESOLVER_SECRET"):
                    self._note("  A SECOND key, different from the platform key (the deposit escrow's dispute resolver).")
                    while True:
                        value = self._stellar_key(env, "LOWBID_DEPOSIT_RESOLVER_SECRET", "LOWBID_DEPOSIT_RESOLVER_SECRET (S…)", kind="secret")
                        if not value or value != env.get("LOWBID_PLATFORM_SECRET"):
                            break
                        self.stdout.write(self.style.ERROR("    must differ from LOWBID_PLATFORM_SECRET"))
                    env.set("LOWBID_DEPOSIT_RESOLVER_SECRET", value)
                if ask("LOWBID_GUARANTEE_FUND_ADDRESS"):
                    self._note("  Public wallet receiving forfeited deposits (needs the asset trustline, != platform).")
                    while True:
                        value = self._stellar_key(env, "LOWBID_GUARANTEE_FUND_ADDRESS", "LOWBID_GUARANTEE_FUND_ADDRESS (G…)", kind="address")
                        if not value or value != env.get("LOWBID_PLATFORM_ADDRESS"):
                            break
                        self.stdout.write(self.style.ERROR("    must differ from LOWBID_PLATFORM_ADDRESS"))
                    env.set("LOWBID_GUARANTEE_FUND_ADDRESS", value)

        if full:
            self._section("Optional")
            self._note("  GitHub token: raises the api.github.com rate limit for the « Verified GitHub » badge.")
            env.set("LOWBID_GITHUB_TOKEN", self._ask("LOWBID_GITHUB_TOKEN", env.get("LOWBID_GITHUB_TOKEN"), secret=True))
            if self._yes("Set the demo wallets used by `make seed` (your Freighter accounts)?", default=False):
                for key, label in DEMO_KEYS:
                    value = self._stellar_key(env, key, f"{label} (G…)", kind="address")
                    if value:
                        env.set(key, value)
