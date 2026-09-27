-- Plugin-local translations for KoInsight.
-- KOReader's gettext catalog only covers core strings, so plugin strings are
-- looked up here first and fall back to KOReader's gettext (i.e. English).
local gettext = require("gettext")

local translations = {
  sk = {
    ["About KoInsight"] = "O doplnku KoInsight",
    ["Aggressive suspend sync disabled"] = "Agresívna synchronizácia pri uspaní vypnutá",
    ["Aggressive suspend sync enabled"] = "Agresívna synchronizácia pri uspaní zapnutá",
    ["Aggressive sync on suspend (auto Wi-Fi)"] = "Agresívna synchronizácia pri uspaní (automatické Wi-Fi)",
    ["Apply"] = "Použiť",
    ["Cancel"] = "Zrušiť",
    ["Data upload failed."] = "Odoslanie údajov zlyhalo.",
    ["Data uploaded."] = "Údaje boli odoslané.",
    ["Enter the location of your KoInsight server"] = "Zadajte adresu vášho servera KoInsight",
    ["Error during auto sync: "] = "Chyba pri automatickej synchronizácii: ",
    ["Error toggling aggressive sync setting"] = "Chyba pri prepínaní agresívnej synchronizácie",
    ["Error toggling sync setting"] = "Chyba pri prepínaní nastavenia synchronizácie",
    ["Error:"] = "Chyba:",
    ["Info"] = "Informácie",
    ["KoInsight is a sync plugin for KoInsight instances.\n\nPlugin version: %s\n\nSee https://github.com/GeorgeSG/koinsight."] = "KoInsight je synchronizačný doplnok pre inštancie KoInsight.\n\nVerzia doplnku: %s\n\nViac na https://github.com/GeorgeSG/koinsight.",
    ["KoInsight server URL is not configured."] = "URL servera KoInsight nie je nastavená.",
    ["KoInsight settings saved."] = "Nastavenia KoInsight boli uložené.",
    ["KoInsight settings"] = "Nastavenia KoInsight",
    ["KoInsight: Sync all books"] = "KoInsight: Synchronizovať všetky knihy",
    ["No books with annotations found in reading history."] = "V histórii čítania sa nenašli žiadne knihy s poznámkami.",
    ["Please configure the server URL first."] = "Najprv nastavte URL servera.",
    ["Please enter a server URL."] = "Zadajte URL servera.",
    ["Server URL:"] = "URL servera:",
    ["Server error"] = "Chyba servera",
    ["Server response is not valid."] = "Odpoveď servera nie je platná.",
    ["Set server URL"] = "Nastaviť URL servera",
    ["Set suspend connect timeout…"] = "Nastaviť časový limit pripojenia pri uspaní…",
    ["Starting sync..\nScanning reading history for books with annotations."] = "Spúšťam synchronizáciu…\nPrehľadávam históriu čítania a hľadám knihy s poznámkami.",
    ["Success:"] = "Úspech:",
    ["Suspend connect timeout (seconds)"] = "Časový limit pripojenia pri uspaní (sekundy)",
    ["Sync complete!\n%d/%d books synced successfully\n%d failed"] = "Synchronizácia dokončená!\n%d/%d kníh úspešne synchronizovaných\nNeúspešné: %d",
    ["Sync failed: "] = "Synchronizácia zlyhala: ",
    ["Sync on suspend disabled"] = "Synchronizácia pri uspaní vypnutá",
    ["Sync on suspend enabled"] = "Synchronizácia pri uspaní zapnutá",
    ["Sync on suspend"] = "Synchronizovať pri uspaní",
    ["Synchronize data"] = "Synchronizovať údaje",
    ["Syncing: %d/%d books\n%d annotations for current book"] = "Synchronizácia: %d/%d kníh\n%d poznámok v aktuálnej knihe",
    ["The server URL must start with 'http://' or 'https://'.\n\n"] = "URL servera musí začínať na 'http://' alebo 'https://'.\n\n",
    ["Timeout (3..60):"] = "Limit (3..60):",
    ["Timeout saved."] = "Časový limit bol uložený.",
    ["Unable to register device."] = "Zariadenie sa nepodarilo zaregistrovať.",
    ["http://example.com:port"] = "http://priklad.sk:port",
  },
}

local function currentLanguage()
  local lang = gettext.current_lang
  if (not lang or lang == "C") and G_reader_settings then
    lang = G_reader_settings:readSetting("language")
  end
  if not lang then
    return nil
  end
  -- "sk_SK" / "sk-SK" -> "sk"
  return lang:match("^(%a+)")
end

return function(msgid)
  local catalog = translations[currentLanguage()]
  return (catalog and catalog[msgid]) or gettext(msgid)
end
