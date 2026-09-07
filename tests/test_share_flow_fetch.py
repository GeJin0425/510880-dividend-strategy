from pipeline.share_flow import fetch_sse_scale_history


class _Response:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "pageHelp": {
                "data": [
                    {"TRADE_DATE": "2026-09-04", "SCALE": "191.5542"},
                    {"TRADE_DATE": "2026-09-03", "SCALE": "192.1815"},
                ]
            }
        }


class _Session:
    def get(self, url, params, headers, timeout):
        assert params["FUND_CODE"] == "510880"
        assert "sqlId" in params
        return _Response()


def test_fetch_sse_scale_history_parses_and_sorts_rows():
    out = fetch_sse_scale_history(session=_Session())

    assert list(out.index.strftime("%Y-%m-%d")) == ["2026-09-03", "2026-09-04"]
    assert out.iloc[-1]["scale_yi"] == 191.5542
