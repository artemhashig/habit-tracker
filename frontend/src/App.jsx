import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ChevronUp, Feather } from 'lucide-react'
import WeekStrip, { toISO } from './components/WeekStrip.jsx'
import HabitCard from './components/HabitCard.jsx'
import ChatModal from './components/ChatModal.jsx'
import ProgressRing from './components/ProgressRing.jsx'
import useLongPress from './components/useLongPress.js'
import api from './api.js'

// Тематика категорий (по макету): цвет рамки + цвет кружка-шеврона
const CATEGORY_META = {
  Спорт: { border: '#7e2231', circleBg: '#3a1218', icon: '#ff6b60' },
  Саморазвитие: { border: '#8e2c55', circleBg: '#e5a8c6', icon: '#ffffff' },
  Здоровье: { border: '#2e6b4a', circleBg: '#16332a', icon: '#6ee7a8' },
  Учеба: { border: '#8a6420', circleBg: '#3a2a10', icon: '#ffd166' },
  Работа: { border: '#2f5a8f', circleBg: '#12253c', icon: '#7cc0ff' },
  Дом: { border: '#5c4396', circleBg: '#221b3c', icon: '#c4b2ff' },
}
const DEFAULT_META = { border: '#34344c', circleBg: '#26263a', icon: '#c9c9d4' }

const MONTHS_GEN = [
  'января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
  'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря',
]

/** Карточка одной категории: удержание → окно удаления категории. */
function CategorySection({
  name,
  items,
  collapsed,
  progress = 0,
  onToggle,
  onIncrement,
  onHabitLongPress,
  onCategoryLongPress,
}) {
  const meta = CATEGORY_META[name] ?? DEFAULT_META
  const longPress = useLongPress(() => onCategoryLongPress(name))

  return (
    <section
      {...longPress}
      className="rise no-callout select-none rounded-[26px] bg-[#12121a] border p-4"
      style={{ borderColor: meta.border }}
    >
      <div className="flex justify-between items-center px-1 pt-0.5">
        <div className="flex items-center gap-2.5">
          <h2 className="text-[21px] font-extrabold">{name}</h2>
        </div>
        <button
          onClick={() => onToggle(name)}
          aria-label={collapsed ? 'Развернуть' : 'Свернуть'}
          className="w-11 h-11 rounded-full flex items-center justify-center transition-transform active:scale-90"
          style={{ background: meta.circleBg }}
        >
          {/* кольцо категории: закрывается по мере закрытия привычек категории */}
          <ProgressRing size={44} stroke={3} trackColor="rgba(255,255,255,0.16)" color={meta.icon} value={progress}>
            <ChevronUp
              size={18}
              strokeWidth={3}
              style={{ color: meta.icon }}
              className={`transition-transform duration-200 ${collapsed ? 'rotate-180' : ''}`}
            />
          </ProgressRing>
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
  const todayISO = useMemo(() => toISO(new Date()), [])
  const [selected, setSelected] = useState(todayISO) // просматриваемый день (YYYY-MM-DD)
  const [habits, setHabits] = useState(null)
  const [collapsed, setCollapsed] = useState({}) // { [категория]: true }
  const [chatOpen, setChatOpen] = useState(false) // единственное окно дневника
  const [pendingReply, setPendingReply] = useState(null) // проактивный ре-анализ
  const [syncNote, setSyncNote] = useState('Ожидание начала синхронизации...')
  const [toast, setToast] = useState(null) // { text, key } — уведомление
  const [deleteTarget, setDeleteTarget] = useState(null) // { kind: 'habit'|'category', ... }
  const [deleting, setDeleting] = useState(false)
  const toastTimer = useRef(null)

  const refreshHabits = useCallback(
    (afterSync = false) => {
      return api(`/api/habits?date=${selected}`)
        .then((r) => r.json())
        .then((data) => {
          setHabits(data)
          if (Array.isArray(data) && afterSync) setSyncNote('Синхронизация завершена ✓')
        })
        .catch((e) => console.error('Ошибка загрузки:', e))
    },
    [selected],
  )

  useEffect(() => {
    refreshHabits()
  }, [refreshHabits])

  useEffect(() => {
    // Проактивная модель ментального здоровья: если срок контрольной точки вышел,
    // ассистент сам показывает сравнение статистики «до/после» (в окне дневника).
    api('/api/wellbeing/pending')
      .then((r) => r.json())
      .then((p) => {
        if (p.due && p.reply) setPendingReply(p.reply)
      })
      .catch(() => {})
    // Safari для доступности игнорирует user-scalable=no в meta — ловим сам жест:
    // gesturestart = начало щипка двумя пальцами; preventDefault останавливает его
    const blockPinch = (e) => e.preventDefault()
    document.addEventListener('gesturestart', blockPinch)
    return () => {
      clearTimeout(toastTimer.current)
      document.removeEventListener('gesturestart', blockPinch)
    }
  }, [])

  const handleIncrement = useCallback(
    (id) => {
      // оптимистичный отклик: счётчик растёт мгновенно, сервер подтверждает следом
      setHabits((prev) =>
        prev?.map((h) => (h.id === id ? { ...h, current: (h.current || 0) + 1 } : h)) ?? prev,
      )
      // отмечаем выполнение в ПРОСМАТРИВАЕМЫЙ день (вчера / сегодня / …)
      api(`/api/habits/${id}/increment?date=${selected}`, { method: 'POST' })
        .then(async (r) => {
          const updated = await r.json()
          if (updated && updated.id) {
            setHabits((prev) => prev?.map((h) => (h.id === id ? updated : h)) ?? prev)
          }
        })
        .catch((e) => {
          console.error('Ошибка обновления:', e)
          refreshHabits() // сетевой сбой — подтягиваем честное состояние с сервера
        })
    },
    [selected, refreshHabits],
  )

  /* Уведомление-заглушка: новое мгновенно заменяет старое (без наложения) */
  const pulseToast = (text = 'Пока рано') => {
    clearTimeout(toastTimer.current)
    setToast({ text, key: Date.now() })
    toastTimer.current = setTimeout(() => setToast(null), 1900)
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
      const r = await api(url, { method: 'DELETE' })
      if (!r.ok) throw new Error('bad response')
      setDeleteTarget(null)
      await refreshHabits(true)
    } catch {
      pulseToast('Не получилось удалить')
    } finally {
      setDeleting(false)
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

  // Дни недели, на которые что-то запланировано (для кружков в ленте)
  const habitDays = useMemo(
    () => Array.from(new Set((habits ?? []).flatMap((h) => h.days))),
    [habits],
  )

  // Кольцо просматриваемого дня: доля суммарных ОТМЕТОК от суммарного плана
  // (отжимания 10 + прыжки 5 → кольцо растёт 1/15, 2/15 … 15/15)
  const dayProgress = useMemo(() => {
    const rel = (habits ?? []).filter((h) => h.scheduledToday || h.current > 0)
    const total = rel.reduce((s, h) => s + h.target, 0)
    if (total === 0) return 0
    const done = rel.reduce((s, h) => s + Math.min(h.current, h.target), 0)
    return done / total
  }, [habits])

  // Кольцо категории: та же доля, но внутри одной категории (сумма отметок)
  const categoryProgress = useCallback(
    (items) => {
      const rel = items.filter((h) => h.scheduledToday || h.current > 0)
      const total = rel.reduce((s, h) => s + h.target, 0)
      if (total === 0) return 0
      const done = rel.reduce((s, h) => s + Math.min(h.current, h.target), 0)
      return done / total
    },
    [],
  )

  // Завтра и позже — просмотр плана без отметок (выполненного ещё не было)
  const canMark = selected <= todayISO

  // Заголовок в шапке: сегодня / вчера / завтра / «5 августа»
  const title = useMemo(() => {
    if (selected === todayISO) return 'Сегодня'
    const d = new Date(`${selected}T00:00:00`)
    const diff = Math.round((d - new Date(`${todayISO}T00:00:00`)) / 86400000)
    if (diff === 1) return 'Завтра'
    if (diff === -1) return 'Вчера'
    return `${d.getDate()} ${MONTHS_GEN[d.getMonth()]}`
  }, [selected, todayISO])

  const toggleCategory = (name) =>
    setCollapsed((prev) => ({ ...prev, [name]: !prev[name] }))

  return (
    // dvh: видимая высота на iOS; h-full: цепочка 100% для старых Safari,
    // где dvh не поддерживается (иначе в PWA снизу остаётся пустое место);
    // pt-env: контент не заезжает под статус-бар (зарядка/wifi) в PWA-режиме
    <div className="h-full min-h-dvh bg-black text-white flex justify-center font-sans antialiased overflow-x-clip">
      <div className="phone-col relative w-full max-w-md px-4 flex flex-col h-full min-h-dvh pt-[env(safe-area-inset-top)]">
        {/* Шапка: только центрированный заголовок выбранного дня */}
        <header className="app-header relative flex justify-center items-center mt-4 h-12">
          <h1 className="text-[19px] font-extrabold tracking-wide whitespace-nowrap">
            {title}
          </h1>
        </header>

        {/* Лента-скроллер дней: клик → привычки за выбранную дату */}
        <WeekStrip
          activePct={dayProgress}
          habitDays={habitDays}
          selected={selected}
          todayISO={todayISO}
          onSelect={(iso) => setSelected(iso)}
        />

        {/* Карточки категорий */}
        <main className="app-main flex flex-col gap-5 mt-6 pb-36">
          {/* pb: запас под фиксированную нижнюю панель ввода, чтобы карточки не прятались */}
          {groups.map(({ name, items }) => (
            <CategorySection
              key={name}
              name={name}
              items={items}
              collapsed={!!collapsed[name]}
              progress={categoryProgress(items)}
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
                Напиши ассистенту в поле внизу экрана — я сам создам привычки из твоих слов.
              </p>
            </div>
          )}

          {/* Строка синхронизации */}
          <p className="text-center text-[14px] font-semibold text-[#6a6a78] pb-1">
            {syncNote}
          </p>
        </main>

        {/* Нижняя строка: выглядит как поле ввода, нажатие открывает единственный дневник */}
        <div className="fixed bottom-0 inset-x-0 z-40 flex justify-center pointer-events-none">
          <div className="phone-col w-full max-w-md px-4 pt-2 pb-[calc(0.75rem+env(safe-area-inset-bottom))] pointer-events-auto">
            <button
              onClick={() => setChatOpen(true)}
              aria-label="Открыть дневник с ассистентом"
              className="w-full flex items-center gap-2 bg-[#17171f] border border-white/10 rounded-full py-2.5 pl-4 pr-4 shadow-2xl shadow-black/50 transition active:scale-[0.98]"
            >
              <span className="flex-1 text-left text-[16px] font-semibold text-white/35">
                Вылей душу…
              </span>
              <span className="w-10 h-10 -mr-1 rounded-full bg-[#6d63f0] flex items-center justify-center text-white flex-shrink-0">
                <Feather size={17} />
              </span>
            </button>
          </div>
        </div>

        {/* Уведомление-заглушка (кнопка меню): новое заменяет старое */}
        {toast && (
          <div
            key={toast.key}
            className="rise fixed top-[calc(6.25rem+env(safe-area-inset-top))] left-1/2 -translate-x-1/2 z-[70] bg-[#1a1a24] border border-white/10 rounded-full px-5 py-2.5 text-[14px] font-bold text-white/90 shadow-xl pointer-events-none whitespace-nowrap"
          >
            {toast.text}
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

        {/* Единственное окно дневника: история хранится в базе, стирается нельзя */}
        {chatOpen && (
          <ChatModal
            pendingReply={pendingReply}
            onClose={() => setChatOpen(false)}
            onHabitsChanged={() => refreshHabits(true)}
          />
        )}
      </div>
    </div>
  )
}
