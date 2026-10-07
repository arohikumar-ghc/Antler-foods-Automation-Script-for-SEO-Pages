"""Unit tests for the configuration system (Step 2)."""
import pytest

from antler_seo.config import (
    Config,
    ConfigError,
    ENV_BASE_URL,
    ENV_EMAIL,
    ENV_HEADLESS,
    ENV_PASSWORD,
    ENV_SLOW_MO,
    ENV_TIMEOUT,
    DEFAULT_HEADLESS,
    DEFAULT_SLOW_MO_MS,
    DEFAULT_TIMEOUT_MS,
)


def _valid_env(**overrides):
    env = {
        ENV_EMAIL: "user@example.com",
        ENV_PASSWORD: "s3cret-value",
        ENV_BASE_URL: "https://cms.example.com",
    }
    env.update(overrides)
    return env


# --- Valid configuration ---------------------------------------------------


def test_valid_config_minimal():
    config = Config.from_env(env=_valid_env(), load_env_file=False)

    assert config.email == "user@example.com"
    assert config.password == "s3cret-value"
    assert config.base_url == "https://cms.example.com"
    # Non-secret defaults applied.
    assert config.headless is DEFAULT_HEADLESS
    assert config.timeout_ms == DEFAULT_TIMEOUT_MS
    assert config.slow_mo_ms == DEFAULT_SLOW_MO_MS
    assert config.is_valid()


def test_valid_config_with_overrides():
    env = _valid_env(
        **{
            ENV_HEADLESS: "true",
            ENV_TIMEOUT: "45000",
            ENV_SLOW_MO: "0",
            ENV_BASE_URL: "https://cms.example.com/",  # trailing slash stripped
        }
    )
    config = Config.from_env(env=env, load_env_file=False)

    assert config.headless is True
    assert config.timeout_ms == 45000
    assert config.slow_mo_ms == 0
    assert config.base_url == "https://cms.example.com"


def test_redacted_masks_password():
    config = Config.from_env(env=_valid_env(), load_env_file=False)
    redacted = config.redacted()

    assert redacted["password"] == "***"
    assert "s3cret-value" not in str(redacted)


# --- Missing configuration -------------------------------------------------


@pytest.mark.parametrize("missing_var", [ENV_EMAIL, ENV_PASSWORD, ENV_BASE_URL])
def test_missing_required_var_raises(missing_var):
    env = _valid_env()
    del env[missing_var]

    with pytest.raises(ConfigError) as exc:
        Config.from_env(env=env, load_env_file=False)

    assert missing_var in str(exc.value)


def test_empty_required_var_raises():
    env = _valid_env(**{ENV_EMAIL: "   "})

    with pytest.raises(ConfigError) as exc:
        Config.from_env(env=env, load_env_file=False)

    assert ENV_EMAIL in str(exc.value)


def test_all_missing_lists_everything():
    with pytest.raises(ConfigError) as exc:
        Config.from_env(env={}, load_env_file=False)

    message = str(exc.value)
    assert ENV_EMAIL in message
    assert ENV_PASSWORD in message
    assert ENV_BASE_URL in message


# --- Invalid configuration -------------------------------------------------


def test_invalid_timeout_not_integer():
    env = _valid_env(**{ENV_TIMEOUT: "not-a-number"})

    with pytest.raises(ConfigError) as exc:
        Config.from_env(env=env, load_env_file=False)

    assert ENV_TIMEOUT in str(exc.value)


def test_invalid_timeout_too_small():
    env = _valid_env(**{ENV_TIMEOUT: "100"})

    with pytest.raises(ConfigError) as exc:
        Config.from_env(env=env, load_env_file=False)

    assert "timeout_ms" in str(exc.value)


def test_invalid_base_url_scheme():
    env = _valid_env(**{ENV_BASE_URL: "cms.example.com"})

    with pytest.raises(ConfigError) as exc:
        Config.from_env(env=env, load_env_file=False)

    assert "base_url" in str(exc.value)


def test_invalid_slow_mo_negative():
    env = _valid_env(**{ENV_SLOW_MO: "-5"})

    with pytest.raises(ConfigError) as exc:
        Config.from_env(env=env, load_env_file=False)

    assert "slow_mo_ms" in str(exc.value)


def test_validate_method_direct():
    config = Config(email="", password="", base_url="ftp://x", timeout_ms=10)
    errors = config.validate()

    assert any("email" in e for e in errors)
    assert any("password" in e for e in errors)
    assert any("base_url" in e for e in errors)
    assert any("timeout_ms" in e for e in errors)
