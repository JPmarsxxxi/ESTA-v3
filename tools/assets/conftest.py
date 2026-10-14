# test_ddg.py, test_fetch.py, test_openverse.py and test_validate.py are v2's manual one-shot scripts (live
# searches and downloads at import), not tests: keep `pytest tools` from running them.
collect_ignore = ["test_ddg.py", "test_fetch.py", "test_openverse.py", "test_validate.py"]
