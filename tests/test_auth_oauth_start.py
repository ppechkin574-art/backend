"""/auth/oauth/{provider} returns a Google authorize URL with our client_id."""


def test_google_oauth_start_returns_authorize_url(http):
    resp = http.get("/auth/oauth/google")
    assert resp.status_code == 200
    body = resp.json()
    assert "oauth_url" in body
    url = body["oauth_url"]
    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth")
    assert "client_id=1064877712464-" in url
    assert "scope=openid" in url
    assert body["redirect_after_auth"].startswith("kz.aima.aima://")


def test_apple_oauth_start_returns_authorize_url(http):
    resp = http.get("/auth/oauth/apple")
    assert resp.status_code == 200
    body = resp.json()
    assert "oauth_url" in body
    assert body["oauth_url"].startswith("https://appleid.apple.com/auth/authorize")
