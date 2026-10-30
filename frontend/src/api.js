/**
 * Обёртка над fetch: добавляет X-Device-ID к каждому запросу.
 *
 * Идентификатор генерируется один раз и живёт в localStorage браузера —
 * у каждого устройства своя изолированная область привычек и чата на сервере,
 * изменения одного человека никоим образом не видны другим.
 */
function deviceId() {
  let id = null
  try {
    id = localStorage.getItem('grit-device-id')
    if (!id) {
      id =
        crypto.randomUUID?.() ||
        `d-${Date.now()}-${Math.random().toString(36).slice(2)}`
      localStorage.setItem('grit-device-id', id)
    }
  } catch {
    // приватный режим без localStorage: случайный ID на сессию,
    // чтобы данные хотя бы не смешались с чужими
    id = `sess-${Math.random().toString(36).slice(2)}`
  }
  return id
}

export default function api(path, options = {}) {
  return fetch(path, {
    ...options,
    headers: { 'X-Device-ID': deviceId(), ...(options.headers || {}) },
  })
}
