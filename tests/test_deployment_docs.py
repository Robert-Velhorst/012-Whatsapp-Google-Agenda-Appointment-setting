from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_hetzner_is_the_only_documented_cloud_deployment_path():
    target = (ROOT / "DEPLOYMENT_TARGET.md").read_text(encoding="utf-8").lower()
    readme = (ROOT / "README.md").read_text(encoding="utf-8").lower()
    guide = (ROOT / "docs" / "HETZNER_DEPLOYMENT.md").read_text(encoding="utf-8").lower()
    hai = (ROOT / "docs" / "HAI_INTEGRATION.md").read_text(encoding="utf-8").lower()

    assert "hetzner" in target
    assert "do not use unapproved serverless hosting or public-tunnel services for production" in target
    assert "hetzner deployment guide" in readme
    assert "supported production hosting path" in guide
    assert "ngrok is not required" in hai


def test_obsolete_ngrok_launcher_is_not_shipped():
    assert not (ROOT / "windows" / "Start-Ngrok.ps1").exists()
