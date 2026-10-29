import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Menu,
  ChevronUp,
  SendHorizontal,
  Loader2,
  Check,
  X,
} from 'lucide-react'
import WeekStrip from './components/WeekStrip.jsx'
import HabitCard from './components/HabitCard.jsx'
import CreateHabitScreen from './components/CreateHabitScreen.jsx'
import useLongPress from './components/useLongPress.js'

// Тематика категорий (по макету): цвет рамки + цвет кружка-шеврона
const CATEGORY_META = {
  Спорт: { emoji: '🏋️', border: '#7e2231', circleBg: '#3a1218', icon: '#ff6b60' },
  Саморазвитие: { emoji: '🧠', border: '#8e2c55', circleBg: '#e5a8c6', icon: '#ffffff' },
  Здоровье: { emoji: '💊', border: '#2e6b4a', circleBg: '#16332a', icon: '#6ee7a8' },
  Учеба: { emoji: '🎓', border: '#8a6420', circleBg: '#3a2a10', icon: '#ffd166' },
  Работа: { emoji: '💼', border: '#2f5a8f', circleBg: '#12253c', icon: '#7cc0ff' },
  Дом: { emoji: '🏠', border: '#5c4396', circleBg: '#221b3c', icon: '#c4b2ff' },
}
const DEFAULT_META = { emoji: '✨', border: '#34344c', circleBg: '#26263a', icon: '#c9c9d4' }

/** Карточка одной категории: удержание → окно удаления категории. */
function CategorySection({
  name,
  items,
  collapsed,
  onToggle,
  onIncrement,
  onHabitLongPress,
  onCategoryLongPress,
}) {
  const meta = CATEGORY_META[name] ?? {
    ...DEFAULT_META,
    emoji: items[0]?.emoji || DEFAULT_META.emoji,
  }
  const longPress = useLongPress(() => onCategoryLongPress(name))

  return (
    <section
      {...longPress}
      className="rise no-callout select-none rounded-[26px] bg-[#12121a] border p-4"
      style={{ borderColor: meta.border }}
    >
      <div className="flex justify-between items-center px-1 pt-0.5">
        <div className="flex items-center gap-2.5">
          <span className="text-[19px]">{meta.emoji}</span>
          <h2 className="text-[21px] font-extrabold">{name}</h2>
        </div>
        <button
          onClick={() => onToggle(name)}
          aria-label={collapsed ? 'Развернуть' : 'Свернуть'}
          className="w-11 h-11 rounded-full flex items-center justify-center transition-transform active:scale-90"
          style={{ background: meta.circleBg }}
        >
          <ChevronUp
            size={18}
            strokeWidth={3}
            style={{ color: meta.icon }}
            className={`transition-transform duration-200 ${collapsed ? 'rotate-180' : ''}`}
          />
        </button>
      </div>

      {!collapsed && (
        <div className="mt-3.5 flex flex-col gap-3">
          {items.map((habit) => (
            <HabitCard
              key={habit.id}
              habit={habit}
              onIncrement={onIncrement}
              onLongPress={() => onHabitLongPress(habit, items.length === 1)}
            />
          ))}
        </div>
      )}
    </section>
  )
}

export default function App() {
  const [habits, setHabits] = useState(null)
  const [collapsed, setCollapsed] = useState({}) // { [категория]: true }
  const [createOpen, setCreateOpen] = useState(false)
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [assistant, setAssistant] = useState(null) // { content, actions } — карточка ответа
  const [syncNote, setSyncNote] = useState('Ожидание начала синхронизации...')
  const [menuToast, setMenuToast] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState(null) // { kind: 'habit'|'category', ... }
  const [deleting, setDeleting] = useState(false)
  const menuTimer = useRef(null)

  const refreshHabits = useCallback((afterSync = false) => {
    return fetch('/api/habits')
      .then((r) => r.json())
      .then((data) => {
        setHabits(data)
        if (afterSync) setSyncNote('Синхронизация завершена ✓')
      })
      .catch((e) => console.error('Ошибка загрузки:', e))
  }, [])

  useEffect(() => {
    refreshHabits()
    return () => clearTimeout(menuTimer.current)
  }, [refreshHabits])

  const handleIncrement = useCallback(
    (id) => {
      fetch(`/api/habits/${id}/increment`, { method: 'POST' })
        .then(async (r) => {
          const updated = await r.json()
          setHabits((prev) => prev?.map((h) => (h.id === id ? updated : h)) ?? prev)
        })
        .catch((e) => console.error('Ошибка обновления:', e))
    },
    [],
  )

  /* Кнопка слева сверху: уведомление «Пока рано» */
  const pulseMenu = () => {
    setMenuToast(true)
    clearTimeout(menuTimer.current)
    menuTimer.current = setTimeout(() => setMenuToast(false), 1900)
  }

  /* Удаление (диалог по удержанию) */
  const confirmDelete = async () => {
    const t = deleteTarget
    if (!t || deleting) return
    setDeleting(true)
    try {
      const url =
        t.kind === 'habit'
          ? `/api/habits/${t.id}`
          : `/api/categories/${encodeURIComponent(t.name)}`
      const r = await fetch(url, { method: 'DELETE' })
      if (!r.ok) throw new Error('bad response')
      setDeleteTarget(null)
      await refreshHabits(true)
    } catch {
      setAssistant({ content: 'Не получилось удалить. Попробуй ещё раз.', actions: [] })
    } finally {
      setDeleting(false)
    }
  }

  /* Сообщение ассистенту из нижней строки ввода */
  const sendChat = async (e) => {
    e.preventDefault()
    const text = draft.trim()
    if (!text || busy) return
    setDraft('')
    setBusy(true)
    setAssistant(null)
    try {
      const r = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text }),
      })
      const data = await r.json()
      const actions = data.applied || []
      setAssistant({ content: data.reply || 'Принял.', actions })
      if (actions.length > 0) await refreshHabits(true)
    } catch {
      setAssistant({
        content: 'Не получилось связаться с ассистентом. Попробуй ещё раз.',
        actions: [],
      })
    } finally {
      setBusy(false)
    }
  }

  // Группировка по категориям (порядок как в БД)
  const groups = useMemo(() => {
    if (!Array.isArray(habits)) return []
    const acc = new Map()
    for (const h of habits) {
      if (!acc.has(h.category)) acc.set(h.category, [])
      acc.get(h.category).push(h)
    }
    return [...acc.entries()].map(([name, items]) => ({ name, items }))
  }, [habits])

  // Существующие категории — для формы создания (порядок как в БД)
  const categories = useMemo(
    () => (Array.isArray(habits) ? [...new Set(habits.map((h) => h.category))] : []),
    [habits],
  )

  // Дни недели, на которые что-то запланировано (для кружков в ленте)
  const habitDays = useMemo(
    () => Array.from(new Set((habits ?? []).flatMap((h) => h.days))),
    [habits],
  )

  // Прогресс дня: доля закрытых привычек из запланированных на сегодня
  const dayProgress = useMemo(() => {
    const list = (habits ?? []).filter((h) => h.scheduledToday || h.current > 0)
    if (list.length === 0) return 0
    return list.filter((h) => h.status === 'done').length / list.length
  }, [habits])

  const toggleCategory = (name) =>
    setCollapsed((prev) => ({ ...prev, [name]: !prev[name] }))

  return (
    // Центрируем «телефон» по центру экрана, фон — чёрный
    <div className="min-h-screen bg-black text-white flex justify-center font-sans antialiased">
      <div className="relative w-full max-w-md px-4 flex flex-col min-h-screen">
        {/* Шапка */}
        <header className="flex justify-between items-center mt-4">
          <button
            onClick={pulseMenu}
            aria-label="Меню"
            className="bg-[#1a1a24] border border-white/5 p-3 rounded-full text-white transition cursor-pointer hover:bg-[#15151e] active:bg-[#0e0e14]"
          >
            <Menu size={22} />
          </button>
          <h1 className="text-[19px] font-extrabold tracking-wide">Сегодня</h1>
          <button
            onClick={() => setCreateOpen(true)}
            aria-label="Создать привычку"
            className="bg-[#6d63f0] px-4 py-2.5 rounded-[22px] hover:bg-[#5f55e0] transition active:scale-90 shadow-lg shadow-indigo-500/25 text-center leading-[1.05] flex-shrink-0"
          >
            <span className="block text-[13px] font-extrabold text-white">Новая</span>
            <span className="block text-[13px] font-extrabold text-white">привычка</span>
          </button>
        </header>

        {/* Лента дней */}
        <WeekStrip activePct={dayProgress} habitDays={habitDays} />

        {/* Карточки категорий */}
        <main className="flex flex-col gap-5 mt-6 pb-2">
          {groups.map(({ name, items }) => (
            <CategorySection
              key={name}
              name={name}
              items={items}
              collapsed={!!collapsed[name]}
              onToggle={toggleCategory}
              onIncrement={handleIncrement}
              onHabitLongPress={(habit, isLast) =>
                setDeleteTarget({
                  kind: 'habit',
                  id: habit.id,
                  title: habit.title,
                  category: name,
                  isLast,
                })
              }
              onCategoryLongPress={(categoryName) =>
                setDeleteTarget({
                  kind: 'category',
                  name: categoryName,
                  count: items.length,
                })
              }
            />
          ))}

          {habits?.length === 0 && (
            <div className="rounded-[26px] bg-[#12121a] border border-[#2b2b3c] p-6 text-center">
              <p className="text-[15px] font-bold text-white/80">Пока пусто</p>
              <p className="text-[13px] text-white/45 mt-1">
                Напиши ассистенту в поле внизу экрана или нажми «Новая привычка» — всё добавится само.
              </p>
            </div>
          )}

          {/* Строка синхронизации */}
          <p className="text-center text-[14px] font-semibold text-[#6a6a78] pb-1">
            {syncNote}
          </p>
        </main>

        {/* Нижняя строка ввода (как в мессенджере) + карточка ответа ассистента */}
        <div className="fixed bottom-0 inset-x-0 z-40 flex justify-center pointer-events-none">
          <div className="w-full max-w-md px-4 pt-2 pb-[calc(0.75rem+env(safe-area-inset-bottom))] pointer-events-auto flex flex-col gap-2">
            {assistant && (
              <div className="rise relative rounded-[22px] bg-[#17171f] border border-white/10 px-4 pt-3 pb-3.5 shadow-2xl shadow-black/50">
                <button
                  onClick={() => setAssistant(null)}
                  aria-label="Закрыть ответ"
                  className="absolute top-2.5 right-2.5 w-7 h-7 rounded-full flex items-center justify-center text-white/40 hover:text-white/80 transition active:scale-90"
                >
                  <X size={16} />
                </button>
                <div className="flex items-center gap-2 pr-8 mb-1.5">
                  <span className="w-6 h-6 rounded-full bg-[#6d63f0] flex items-center justify-center text-[11px] text-white">
                    ✦
                  </span>
                  <span className="text-[11px] font-extrabold text-[#a79dff] uppercase tracking-widest">
                    Ассистент
                  </span>
                </div>
                <p className="text-[14.5px] leading-snug text-white/90 font-semibold whitespace-pre-line pr-2">
                  {assistant.content}
                </p>
                {assistant.actions.length > 0 && (
                  <div className="flex flex-col gap-1.5 mt-2.5">
                    {assistant.actions.map((a, i) => (
                      <div
                        key={i}
                        className="flex items-start gap-2 bg-[#6d63f0]/15 rounded-xl px-3 py-2"
                      >
                        <Check size={14} className="mt-0.5 text-[#8f85ff] flex-shrink-0" />
                        <span className="text-[13px] font-bold text-white/90 leading-snug">
                          {a.text}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            <form
              onSubmit={sendChat}
              className="flex items-center gap-2 bg-[#17171f] border border-white/10 rounded-full py-1.5 pl-4 pr-1.5 shadow-2xl shadow-black/50"
            >
              <input
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                placeholder="Вылей душу…"
                maxLength={4000}
                enterKeyHint="send"
                className="flex-1 min-w-0 bg-transparent outline-none text-[15px] font-semibold text-white placeholder-white/35 py-2"
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

        {/* Уведомление «пока рано» (кнопка меню) */}
        {menuToast && (
          <div className="rise fixed top-20 left-1/2 -translate-x-1/2 z-[70] bg-[#1a1a24] border border-white/10 rounded-full px-5 py-2.5 text-[14px] font-bold text-white/90 shadow-xl pointer-events-none whitespace-nowrap">
            Пока рано
          </div>
        )}

        {/* Окно удаления (по удержанию) */}
        {deleteTarget && (
          <div
            className="fixed inset-0 z-[60] bg-black/70 flex items-end justify-center px-5 pb-8"
            onClick={() => !deleting && setDeleteTarget(null)}
          >
            <div
              onClick={(e) => e.stopPropagation()}
              className="rise w-full max-w-sm rounded-[26px] bg-[#17171f] border border-white/10 p-5 flex flex-col gap-3 shadow-2xl"
            >
              <h3 className="text-[18px] font-extrabold leading-snug pr-6">
                {deleteTarget.kind === 'habit'
                  ? `Удалить привычку «${deleteTarget.title}»?`
                  : `Удалить категорию «${deleteTarget.name}»?`}
              </h3>
              <p className="text-[14px] font-semibold text-white/55 leading-snug">
                {deleteTarget.kind === 'habit'
                  ? deleteTarget.isLast
                    ? `Это последняя привычка в «${deleteTarget.category}» — категория тоже исчезнет.`
                    : 'Уйдёт сама привычка и весь её прогресс.'
                  : `Все привычки в ней (${deleteTarget.count} шт.) удалятся вместе с категорией.`}
              </p>
              <div className="flex gap-2.5 mt-1">
                <button
                  onClick={() => setDeleteTarget(null)}
                  disabled={deleting}
                  className="flex-1 py-3 rounded-full bg-[#26263a] text-white font-extrabold text-[15px] transition active:scale-95 disabled:opacity-50"
                >
                  Отмена
                </button>
                <button
                  onClick={confirmDelete}
                  disabled={deleting}
                  className="flex-1 py-3 rounded-full bg-[#e5484d] text-white font-extrabold text-[15px] transition active:scale-95 disabled:opacity-50"
                >
                  {deleting ? 'Удаляю…' : 'Удалить'}
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Экран «Новая привычка» */}
        {createOpen && (
          <CreateHabitScreen
            categories={categories}
            onClose={() => setCreateOpen(false)}
            onCreated={() => {
              setCreateOpen(false)
              refreshHabits(true)
            }}
            onError={(msg) =>
              setAssistant({ content: `Не получилось: ${msg}`, actions: [] })
            }
          />
        )}
      </div>
    </div>
  )
}
