from nicegui.testing import User

from aerosuite.web import config


async def test_home_page_renders(user: User, tmp_path):
    await user.open("/")
    await user.should_see("AeroSuite")
    assert config.root() == tmp_path.resolve()
