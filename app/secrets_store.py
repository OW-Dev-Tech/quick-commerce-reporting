"""Passwords live only in the OS keychain (Keychain / Credential Manager) on this laptop."""
import keyring

SERVICE = "qc-reporting"


def _k(brand, platform):
    return f"{brand}|{platform}"


def set_password(brand, platform, pw):
    keyring.set_password(SERVICE, _k(brand, platform), pw)


def get_password(brand, platform):
    return keyring.get_password(SERVICE, _k(brand, platform))


def has_password(brand, platform):
    return bool(get_password(brand, platform))
