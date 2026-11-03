import { useEffect, useRef } from 'react'

const WEEKDAY_RU = ['Вс', 'Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб']

// длина окружности кольца (r = 18)
const RING_CIRC = 2 * Math.PI * 18

function shiftDay(base, offset) {
  const d = new Date(base)
  d.setDate(d.getDate() + offset)
  return d
}

/** Локальная дата → YYYY-MM-DD (без UTC-сдвигов toISOString). */
export function toISO(d) {
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}

/**
 * Календарь-скроллер дней: две недели назад … завтра.
 * Клик по дню выбирает его — экран перезагружает привычки за выбранную дату
 * (вчера / сегодня / завтра и далее по ленте). Выбранный день автоподкручивается.
 * activePct — доля закрытых привычек за выбранный день (кольцо).
 */
export default function WeekStrip({ activePct = 0, habitDays = [], selected, todayISO, onSelect }) {
  const scrollerRef = useRef(null)
  const today = new Date()
  const days = []

  for (let offset = -13; offset <= 1; offset++) {
    const d = shiftDay(today, offset)
    const iso = toISO(d)
    days.push({
      iso,
      code: WEEKDAY_RU[d.getDay()],
      num: d.getDate(),
      isToday: iso === todayISO,
      isSelected: iso === selected,
    })
  }

  // Автопрокрутка к выбранному дню при смене (и при первом открытии)
  useEffect(() => {
    const el = scrollerRef.current
    const node = el?.querySelector('[data-selected="true"]')
    if (el && node) {
      el.scrollTo({
        left: node.offsetLeft - el.clientWidth / 2 + node.offsetWidth / 2,
        behavior: 'smooth',
      })
    }
  }, [selected, todayISO])

  const scheduledSet = new Set(habitDays)

  return (
    <div
      ref={scrollerRef}
      className="week-strip no-scrollbar flex justify-start items-end gap-1.5 mt-5 select-none overflow-x-auto"
    >
      {days.map(({ iso, code, num, isToday, isSelected }) => {
        if (isToday) {
          const active = isSelected
          return (
            <button
              key={iso}
              type="button"
              data-selected={active}
              onClick={() => onSelect?.(iso)}
              aria-label={`Сегодня, ${num}`}
              className={`today-card flex-shrink-0 flex flex-col items-center justify-between w-16 h-[6.5rem] rounded-[26px] py-3 shadow-lg transition ${
                active
                  ? 'bg-[#6d63f0] shadow-indigo-500/25'
                  : 'bg-[#26263a] shadow-black/20'
              }`}
            >
              <span className="text-[13px] font-extrabold text-white">{code}</span>
              <div className="relative w-9 h-9 flex items-center justify-center">
                <svg viewBox="0 0 40 40" className="absolute inset-0 -rotate-90">
                  {/* прогресс вокруг белого круга */}
                  <circle
                    cx="20"
                    cy="20"
                    r="18"
                    fill="none"
                    stroke="rgba(255,255,255,0.35)"
                    strokeWidth="2.5"
                  />
                  <circle
                    cx="20"
                    cy="20"
                    r="18"
                    fill="none"
                    stroke={active ? '#ffffff' : '#8f85ff'}
                    strokeWidth="3"
                    strokeLinecap="round"
                    strokeDasharray={`${activePct * RING_CIRC} ${RING_CIRC}`}
                  />
                </svg>
                <span className="text-[15px] font-extrabold text-white">{num}</span>
              </div>
            </button>
          )
        }

        const scheduled = scheduledSet.has(code)
        const active = isSelected

        if (active) {
          // выбранный (не сегодняшний) день — залит тем же фиолетовым
          return (
            <button
              key={iso}
              type="button"
              data-selected="true"
              onClick={() => onSelect?.(iso)}
              aria-label={`${code}, ${num}`}
              className="day-cell flex-shrink-0 flex flex-col items-center gap-1 w-9 transition-transform active:scale-90"
            >
              <span className="text-[13px] font-bold text-white/70">{code}</span>
              <div className="day-circle w-9 h-9 rounded-full bg-[#6d63f0] flex items-center justify-center">
                <span className="text-[14px] font-extrabold text-white">{num}</span>
              </div>
            </button>
          )
        }

        return (
          <button
            key={iso}
            type="button"
            onClick={() => onSelect?.(iso)}
            aria-label={`${code}, ${num}`}
            className="day-cell flex-shrink-0 flex flex-col items-center gap-1 w-9 transition-transform active:scale-90"
          >
            <span className={`text-[13px] font-bold ${scheduled ? 'text-white/60' : 'text-white/35'}`}>
              {code}
            </span>
            <div
              className={`day-circle h-9 w-9 rounded-full flex items-center justify-center ${
                scheduled ? 'bg-[#181928] border border-[#272848]' : 'bg-transparent'
              }`}
            >
              <span className="text-[14px] font-extrabold text-white/80">{num}</span>
            </div>
          </button>
        )
      })}
    </div>
  )
}
