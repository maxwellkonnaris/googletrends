offline_backend <- function() {
  testthat::skip_if(Sys.getenv("TRENDSPULL_REQUIRE_R") != "1", "Set TRENDSPULL_REQUIRE_R=1 with an installed Python backend")
  reticulate::py_run_string(paste(
    "import json, requests, trendspull._api as api",
    "from unittest.mock import Mock",
    "requests.sessions.Session.request = Mock(side_effect=AssertionError('Unexpected network access'))",
    "rows = [dict(time=str(1609632000 + i*604800), value=v, formattedValue=list(map(str,v))) for i,v in enumerate([[100,20],[50,0],[25,5]])]",
    "client = Mock()",
    "client.timeline.return_value = ('{}', json.dumps({'default': {'timelineData': rows}}), 'WEEK')",
    "api._TrendsClient = Mock(return_value=client)",
    "api.time.sleep = Mock()", sep = "\n"
  ))
}
