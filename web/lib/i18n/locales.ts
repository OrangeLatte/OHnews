/** 21 语言元数据闭集（M5 需求①）。dir 驱动 RTL（ar/fa）。 */

export type Dir = "ltr" | "rtl";

export interface LocaleMeta {
  code: string;
  name: string; // 语言自称（选项显示用）
  en: string;
  dir: Dir;
}

export const LOCALES: LocaleMeta[] = [
  { code: "en", name: "English", en: "English", dir: "ltr" },
  { code: "zh", name: "简体中文", en: "Mandarin Chinese", dir: "ltr" },
  { code: "fr", name: "Français", en: "French", dir: "ltr" },
  { code: "es", name: "Español", en: "Spanish", dir: "ltr" },
  { code: "ar", name: "العربية", en: "Arabic", dir: "rtl" },
  { code: "ru", name: "Русский", en: "Russian", dir: "ltr" },
  { code: "de", name: "Deutsch", en: "German", dir: "ltr" },
  { code: "ja", name: "日本語", en: "Japanese", dir: "ltr" },
  { code: "pt", name: "Português", en: "Portuguese", dir: "ltr" },
  { code: "hi", name: "हिन्दी", en: "Hindi", dir: "ltr" },
  { code: "ko", name: "한국어", en: "Korean", dir: "ltr" },
  { code: "it", name: "Italiano", en: "Italian", dir: "ltr" },
  { code: "tr", name: "Türkçe", en: "Turkish", dir: "ltr" },
  { code: "nl", name: "Nederlands", en: "Dutch", dir: "ltr" },
  { code: "pl", name: "Polski", en: "Polish", dir: "ltr" },
  { code: "sv", name: "Svenska", en: "Swedish", dir: "ltr" },
  { code: "fa", name: "فارسی", en: "Persian (Farsi)", dir: "rtl" },
  { code: "id", name: "Bahasa Indonesia", en: "Indonesian", dir: "ltr" },
  { code: "vi", name: "Tiếng Việt", en: "Vietnamese", dir: "ltr" },
  { code: "bn", name: "বাংলা", en: "Bengali", dir: "ltr" },
  { code: "yue", name: "廣東話", en: "Cantonese", dir: "ltr" },
];

export const DEFAULT_LOCALE = "en";
export const RTL_LOCALES = new Set(LOCALES.filter((l) => l.dir === "rtl").map((l) => l.code));

export function localeMeta(code: string): LocaleMeta {
  return LOCALES.find((l) => l.code === code) ?? LOCALES[0];
}

export function isLocale(code: string): boolean {
  return LOCALES.some((l) => l.code === code);
}

export function dirOf(code: string): Dir {
  return RTL_LOCALES.has(code) ? "rtl" : "ltr";
}
