import runpy


def test_cloud_configuration_is_safe_and_complete() -> None:
    module = runpy.run_path("scripts/validate_cloud_config.py")
    module["main"]()
