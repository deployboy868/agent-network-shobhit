"""Microsoft Teams integration: bot + Graph presence.

Heavy dependencies (botbuilder, msal, aiohttp) are imported lazily inside the
modules so importing the rest of the package never requires them.
"""
