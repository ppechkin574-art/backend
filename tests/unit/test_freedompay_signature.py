"""HMAC-MD5 signature for FreedomPay webhooks.

Critical: if verify_pg_sig is broken, anyone can POST a fake "payment
success" webhook and activate a paid subscription for free.

verify_pg_sig is a pure function (hashlib only) — easy to unit test.
"""

from clients.freedom_pay.client import make_pg_sig, verify_pg_sig


SCRIPT = "result.php"
SECRET = "test-merchant-secret"


def test_make_pg_sig_deterministic_for_same_input():
    params = {"pg_order_id": "42", "pg_amount": "1990"}
    sig1 = make_pg_sig(params, SCRIPT, SECRET)
    sig2 = make_pg_sig(params, SCRIPT, SECRET)
    assert sig1 == sig2
    assert len(sig1) == 32  # MD5 hex


def test_make_pg_sig_changes_when_secret_changes():
    params = {"pg_order_id": "42"}
    sig_a = make_pg_sig(params, SCRIPT, "secret-A")
    sig_b = make_pg_sig(params, SCRIPT, "secret-B")
    assert sig_a != sig_b


def test_make_pg_sig_changes_when_amount_changes():
    sig_low = make_pg_sig({"pg_order_id": "42", "pg_amount": "100"}, SCRIPT, SECRET)
    sig_high = make_pg_sig({"pg_order_id": "42", "pg_amount": "999999"}, SCRIPT, SECRET)
    assert sig_low != sig_high


def test_make_pg_sig_independent_of_dict_key_order():
    """Keys are sorted internally — signature must not depend on insertion order."""
    forward = make_pg_sig({"a": "1", "b": "2", "c": "3"}, SCRIPT, SECRET)
    reverse = make_pg_sig({"c": "3", "b": "2", "a": "1"}, SCRIPT, SECRET)
    assert forward == reverse


def test_make_pg_sig_skips_pg_sig_field_itself():
    """pg_sig is stripped from the payload before hashing — otherwise verify
    would fail for legitimate FreedomPay callbacks (which include their own
    pg_sig in the payload)."""
    without = make_pg_sig({"pg_order_id": "42"}, SCRIPT, SECRET)
    with_sig = make_pg_sig(
        {"pg_order_id": "42", "pg_sig": "anything"}, SCRIPT, SECRET
    )
    assert without == with_sig


def test_make_pg_sig_skips_empty_string_values():
    a = make_pg_sig({"pg_order_id": "42"}, SCRIPT, SECRET)
    b = make_pg_sig({"pg_order_id": "42", "pg_status": ""}, SCRIPT, SECRET)
    # Empty string values are filtered out per the implementation contract.
    assert a == b


def test_verify_pg_sig_accepts_correct_signature():
    params = {"pg_order_id": "42", "pg_amount": "1990"}
    correct = make_pg_sig(params, SCRIPT, SECRET)
    assert verify_pg_sig(params, SCRIPT, SECRET, correct) is True


def test_verify_pg_sig_rejects_wrong_signature():
    params = {"pg_order_id": "42", "pg_amount": "1990"}
    assert verify_pg_sig(params, SCRIPT, SECRET, "deadbeef" * 4) is False


def test_verify_pg_sig_rejects_empty_signature():
    params = {"pg_order_id": "42"}
    assert verify_pg_sig(params, SCRIPT, SECRET, "") is False


def test_verify_pg_sig_rejects_signature_when_amount_was_tampered():
    """The high-impact attack scenario: attacker captures a real callback,
    replays it with pg_amount lowered. verify_pg_sig must reject."""
    real_params = {"pg_order_id": "42", "pg_amount": "1990"}
    real_sig = make_pg_sig(real_params, SCRIPT, SECRET)
    tampered = {"pg_order_id": "42", "pg_amount": "1"}
    assert verify_pg_sig(tampered, SCRIPT, SECRET, real_sig) is False
