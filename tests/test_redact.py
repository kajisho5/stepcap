import pytest

from stepcap.redact import PATTERNS, leak_kinds, luhn_ok, redact_obj, redact_text

GH = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"
GH_PAT = "github_pat_" + "11ABCDEFG0123456789_abcdefghijklmnopqrstuvwxyz"
AWS = "AKIA" + "IOSFODNN7EXAMPLE"
OPENAI = "sk-proj-" + "abcdefghijklmnopqrstuvwxyz012345"
ANTHROPIC = "sk-ant-api03-" + "abcdefghijklmnopqrstuvwxyz0123456789"
JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
CARD = "4242 4242 4242 4242"


@pytest.mark.parametrize(
    ("secret", "kind"),
    [
        (GH, "github-token"),
        (GH_PAT, "github-token"),
        (AWS, "aws-access-key"),
        (OPENAI, "openai-key"),
        (ANTHROPIC, "anthropic-key"),
        (JWT, "jwt"),
        (CARD, "card"),
        ("4242-4242-4242-4242", "card"),
        ("3056 9309 0259 04", "card"),  # 14-digit Diners test number
    ],
)
def test_secret_is_replaced(secret, kind):
    text = f"before {secret} after"
    out = redact_text(text)
    assert secret not in out
    assert f"[REDACTED:{kind}]" in out
    assert out.startswith("before ") and out.endswith(" after")
    assert leak_kinds(text) and not leak_kinds(out)


def test_url_password_and_token_params():
    url = "https://admin:hunter2@example.com/login?user=bob&password=hunter2&token=abc123#x"
    out = redact_text(url)
    assert "hunter2" not in out and "abc123" not in out
    assert "user=bob" in out and "example.com/login" in out
    assert leak_kinds(url) and not leak_kinds(out)


def test_ordinary_text_is_untouched():
    for text in (
        "Order 1234 5678 shipped",  # too short for a card
        "4242 4242 4242 4241",  # fails the Luhn check
        "0000 0000 0000 0000",  # one repeated digit
        "Version 1.2.3.4567890123456",
        "https://example.com/search?q=token",
        "sk-short",
        "Click the Keys tab",
        "recorded-procedure-20260925-055333",  # a date-time name that passes Luhn
        "20260925055333",
    ):
        assert redact_text(text) == text, text
        assert leak_kinds(text) == [], text


def test_prefixed_tokens_glued_to_text():
    assert redact_text("xx" + GH) == "xx[REDACTED:github-token]"
    assert redact_text("key:" + ANTHROPIC) == "key:[REDACTED:anthropic-key]"


def test_luhn():
    assert luhn_ok("4242424242424242")
    assert not luhn_ok("4242424242424241")


def test_redact_obj_keeps_structure_and_ids():
    ev = {
        "id": 3,
        "kind": "type",
        "screenshot": "raw/0003.png",
        "text": f"token {GH}",
        "nested": [{"note": CARD}],
    }
    out = redact_obj(ev)
    assert out["id"] == 3 and out["kind"] == "type" and out["screenshot"] == "raw/0003.png"
    assert GH not in out["text"] and out["nested"][0]["note"] == "[REDACTED:card]"
    assert ev["text"].endswith(GH)  # input not mutated


def test_leak_kinds_returns_labels_only():
    labels = {k for k, _ in PATTERNS}
    labels |= {"url-password", "url-param", "card"}
    found = leak_kinds(f"{GH} {AWS} https://a:b@x.io/?token=zz {CARD}")
    assert found and set(found) <= labels
    assert not any(s in " ".join(found) for s in (GH, AWS, "zz", CARD))
