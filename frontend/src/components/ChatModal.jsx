import { useEffect, useRef, useState } from 'react'
import { X, SendHorizontal, Loader2, Check } from 'lucide-react'
import api from '../api.js'

/**
 * Единственное диалоговое окно с ассистентом.
 *  - открывается по нажатию на строку ввода на главном экране;
 *  - вся история чата хранится в базе и загружается при каждом открытии —
 *    удалить или стереть переписку из интерфейса невозможно;
 *  - крестик сверху закрывает окно (история сохраняется);
 *  - ассистент вызывает функции бэкенда (создание/изменение/удаление
 *    привычек) — применённые действия показываются чипами под ответом.
 * pendingReply — проактивное сообщение ре-анализа wellbeing (один раз за визит).
 */
export default function ChatModal({ pendingReply, onClose, onHabitsChanged }) {
  const [messages, setMessages] = useState(null) // null = история грузится
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const listRef = useRef(null)
  const inputRef = useRef(null)
  const bottomRef = useRef(null)

  const loadHistory = () =>
    api('/api/chat/history')
      .then((r) => r.json())
      .then((h) => setMessages(Array.isArray(h) ? h : []))
      .catch(() => setMessages([]))

  useEffect(() => {
    loadHistory()
    // фокус на поле: окно открывается «на ввод», клавиатура поднимается сразу
    const t = setTimeout(() => inputRef.current?.focus(), 350)
    return () => clearTimeout(t)
  }, [])

  // автоскролл вниз: история загрузилась, пришёл ответ, печатает…
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: 'end' })
  }, [messages, busy])

  const send = async (e) => {
    e.preventDefault()
    const text = draft.trim()
    if (!text || busy) return
    setDraft('')
    setBusy(true)
    // оптимистично показываем своё сообщение, историю выверяем по серверу после ответа
    setMessages((prev) => [
      ...(prev || []),
      { id: `local-${Date.now()}`, role: 'user', content: text, actions: [] },
    ])
    try {
      const r = await api('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text }),
      })
      const data = await r.json()
      await loadHistory() // единственный источник правды — база
      if (data.applied?.length) onHabitsChanged?.()
    } catch {
      setMessages((prev) => [
        ...(prev || []),
        {
          id: `err-${Date.now()}`,
          role: 'assistant',
          content: 'Не получилось связаться с ассистентом. Попробуй ещё раз.',
          actions: [],
        },
      ])
    } finally {
      setBusy(false)
    }
  }

  const bubble = (m, i) => {
    const isUser = m.role === 'user'
    return (
      <div key={m.id ?? i} className={`flex flex-col ${isUser ? 'items-end' : 'items-start'} gap-1 max-w-[85%]`}>
        <div
          className={
            isUser
              ? 'rise rounded-[18px] rounded-br-[6px] bg-[#6d63f0] px-4 py-2.5 text-[14.5px] leading-snug font-semibold text-white whitespace-pre-line'
              : 'rise rounded-[18px] rounded-bl-[6px] bg-[#17171f] border border-white/10 px-4 py-2.5 text-[14.5px] leading-snug text-white/90 font-medium whitespace-pre-line'
          }
        >
          {m.content}
        </div>
        {!isUser && m.actions?.length > 0 && (
          <div className="flex flex-col gap-1 w-full">
            {m.actions.map((a, j) => (
              <div
                key={j}
                className="flex items-start gap-2 bg-[#6d63f0]/15 rounded-xl px-3 py-2"
              >
                <Check size={14} className="mt-0.5 text-[#8f85ff] flex-shrink-0" />
                <span className="text-[13px] font-bold text-white/90 leading-snug">{a.text}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    )
  }

  return (
    <div className="fixed inset-0 z-[80] bg-black flex justify-center">
      <div className="phone-col relative w-full max-w-md h-full min-h-dvh flex flex-col pt-[env(safe-area-inset-top)]">
        {/* Шапка: крестик сверху, заголовок центрируется по экрану */}
        <header className="app-header relative flex items-center justify-between px-4 mt-3 pb-3 border-b border-white/7">
          <span className="w-11" aria-hidden="true" />
          <div className="absolute left-1/2 -translate-x-1/2 top-1/2 -translate-y-1/2 pointer-events-none">
            <h1 className="text-[16px] font-extrabold tracking-wide text-white/85 whitespace-nowrap">
              Дневник с ассистентом
            </h1>
          </div>
          <button
            onClick={onClose}
            aria-label="Закрыть дневник"
            className="w-11 h-11 rounded-full bg-[#1a1a24] border border-white/5 flex items-center justify-center text-white/70 transition hover:bg-[#15151e] active:scale-90"
          >
            <X size={20} />
          </button>
        </header>

        {/* Лента сообщений: только Bot + ты, удалить ничего нельзя */}
        <div ref={listRef} className="flex-1 overflow-y-auto no-scrollbar px-4 py-4">
          <div className="flex flex-col gap-2.5">
            {messages === null && (
              <div className="flex justify-center py-8">
                <Loader2 size={22} className="animate-spin text-white/30" />
              </div>
            )}
            {Array.isArray(messages) && messages.length === 0 && (
              <div className="self-start max-w-[85%] rounded-[18px] rounded-bl-[6px] bg-[#17171f] border border-white/10 px-4 py-2.5">
                <p className="text-[14.5px] leading-snug text-white/80 font-medium">
                  Привет! Вылей душу — я разберу её и переложу в привычки: создам,
                  упрощу, поставлю на паузу. Всё, что ты пишешь, сохраняется здесь.
                </p>
              </div>
            )}
            {Array.isArray(messages) && messages.map(bubble)}
            {pendingReply && bubble({ id: 'pending', role: 'assistant', content: pendingReply, actions: [] })}
            {busy && (
              <div className="self-start bg-[#17171f] border border-white/10 rounded-[18px] rounded-bl-[6px] px-4 py-3 flex gap-1">
                <span className="typing-dot w-1.5 h-1.5 rounded-full bg-white/60" />
                <span className="typing-dot w-1.5 h-1.5 rounded-full bg-white/60" />
                <span className="typing-dot w-1.5 h-1.5 rounded-full bg-white/60" />
              </div>
            )}
            <div ref={bottomRef} />
          </div>
        </div>

        {/* Ввод: тот же стиль, что на главном экране */}
        <form
          onSubmit={send}
          className="flex items-center gap-2 bg-[#17171f] border border-white/10 rounded-full py-1.5 pl-4 pr-1.5 mx-4 mb-3 pb-[env(safe-area-inset-bottom)] shadow-2xl shadow-black/50"
        >
          <input
            ref={inputRef}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onFocus={(e) =>
              // iOS: клавиатура сдвигает визуальную область — подводим ленту к полю
              setTimeout(
                () => e.target.scrollIntoView({ block: 'end', behavior: 'smooth' }),
                250,
              )
            }
            placeholder="Вылей душу…"
            maxLength={4000}
            enterKeyHint="send"
            className="flex-1 min-w-0 bg-transparent outline-none text-[16px] font-semibold text-white placeholder-white/35 py-2"
          />
          <button
            type="submit"
            disabled={busy || !draft.trim()}
            aria-label="Отправить"
            className="w-10 h-10 rounded-full bg-[#6d63f0] disabled:bg-[#26263a] flex items-center justify-center text-white transition active:scale-90 flex-shrink-0"
          >
            {busy ? <Loader2 size={17} className="animate-spin" /> : <SendHorizontal size={17} />}
          </button>
        </form>
      </div>
    </div>
  )
}
