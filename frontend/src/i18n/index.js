import { createI18n } from 'vue-i18n'
import languages from '../../../locales/languages.json'

const localeFiles = import.meta.glob('../../../locales/!(languages).json', { eager: true })

const messages = {}
const availableLocales = []

for (const path in localeFiles) {
  const match = path.match(/\/([^/]+)\.json$/)
  if (match) {
    const key = match[1]
    if (languages[key]) {
      messages[key] = localeFiles[path].default
      availableLocales.push({ key, label: languages[key].label })
    }
  }
}

// Forzar siempre español
try {
  localStorage.setItem('locale', 'es')
} catch (e) {}

const i18n = createI18n({
  legacy: false,
  locale: 'es',
  fallbackLocale: 'es',
  messages
})

export { availableLocales }
export default i18n
