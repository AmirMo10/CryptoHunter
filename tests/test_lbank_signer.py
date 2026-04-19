"""Unit tests for the LBank signer.

The reference fixture is lifted verbatim from the LBank Contract API PDF
("Introduction - LBank CONTRACT API") - the "SUBMIT" section shows the full
sorted parameter string and the expected `sign` value. Reproducing this
byte-for-byte is the contract we must not break without deliberate action.
"""

from __future__ import annotations

import pytest

from cryptohunter.exchanges.lbank import (
    ECHOSTR_MAX,
    ECHOSTR_MIN,
    SIGMETHOD_HMAC,
    SIGMETHOD_RSA,
    LBankSigner,
    generate_echostr,
)

# Fixtures from the PDF's signing example.
DOC_API_KEY = "fb4e39e5-6a06-4291-9f80-d10176a0badd"
DOC_SECRET = "093F44F700FC48F17DDB67390C895CE5"
DOC_PARAMS = {
    "api_key": DOC_API_KEY,
    "asset": "USDT",
    "echostr": "echostr123456789012345678901234567890",
    "productGroup": "SwapU",
    "signature_method": "HmacSHA256",
    "timestamp": "1665990154559",
}
DOC_EXPECTED_PARAMS_STR = (
    "api_key=fb4e39e5-6a06-4291-9f80-d10176a0badd"
    "&asset=USDT"
    "&echostr=echostr123456789012345678901234567890"
    "&productGroup=SwapU"
    "&signature_method=HmacSHA256"
    "&timestamp=1665990154559"
)
DOC_EXPECTED_SIGN = "809133cb69a17beba0be076b99b4d90de872476e36da87978ab2889970ccd06d"


def test_build_parameters_sorts_alphabetically_and_drops_sign() -> None:
    params = dict(DOC_PARAMS)
    params["sign"] = "should-be-removed"
    assert LBankSigner.build_parameters(params) == DOC_EXPECTED_PARAMS_STR


def test_prepared_str_is_upper_md5_hex() -> None:
    # MD5 of the documented parameters string must be uppercase hex (32 chars).
    prepared = LBankSigner.prepared_str(DOC_EXPECTED_PARAMS_STR)
    assert len(prepared) == 32
    assert prepared == prepared.upper()


def test_sign_reproduces_pdf_documented_example() -> None:
    """This is THE contract test. If it breaks, every signed request will be rejected."""
    signer = LBankSigner(DOC_API_KEY, DOC_SECRET)
    assert signer.sign(DOC_PARAMS) == DOC_EXPECTED_SIGN


def test_sign_is_stable_when_sign_key_is_already_present() -> None:
    signer = LBankSigner(DOC_API_KEY, DOC_SECRET)
    params_with_sign = dict(DOC_PARAMS)
    params_with_sign["sign"] = "stale-value-from-prior-request"
    assert signer.sign(params_with_sign) == DOC_EXPECTED_SIGN


def test_rsa_signing_raises_not_implemented() -> None:
    with pytest.raises(NotImplementedError):
        LBankSigner(DOC_API_KEY, DOC_SECRET, signature_method=SIGMETHOD_RSA)


def test_unknown_signature_method_raises() -> None:
    with pytest.raises(ValueError, match="unsupported signature_method"):
        LBankSigner(DOC_API_KEY, DOC_SECRET, signature_method="MD5")


def test_signature_method_constants() -> None:
    assert SIGMETHOD_HMAC == "HmacSHA256"
    assert SIGMETHOD_RSA == "RSA"


@pytest.mark.parametrize("length", [ECHOSTR_MIN, 36, ECHOSTR_MAX])
def test_generate_echostr_length_in_range(length: int) -> None:
    es = generate_echostr(length)
    assert len(es) == length
    assert es.isalnum()


def test_generate_echostr_rejects_out_of_range() -> None:
    with pytest.raises(ValueError, match="echostr length"):
        generate_echostr(ECHOSTR_MIN - 1)
    with pytest.raises(ValueError, match="echostr length"):
        generate_echostr(ECHOSTR_MAX + 1)


def test_generate_echostr_is_random() -> None:
    samples = {generate_echostr() for _ in range(50)}
    assert len(samples) == 50
