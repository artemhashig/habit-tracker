import { useEffect, useRef } from 'react'
import ProgressRing from './ProgressRing.jsx'

const WEEKDAY_RU = ['Вс', 'Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб']

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
 * Выбранный день — фиолетовая «пилюля»: код дня недели сверху, внутри белый
 * кружок с числом и кольцо прогресса, которое закрывается по мере закрытия
 * привычек за день (от пустого кольца до полного круга).
 * Клик по дню выбирает его — экран перезагружает привычки за выбранную дату.
 */
export default function WeekStrip({ activePct = 0, habitDays = [], selected, onSelect }) {
  const scrollerRef = useRef(null)
  const today = new Date()
  const todayISO = toISO(today)
  const days = []

  for (let offset = -13; offset <= 1; offset++) {
    const d = shiftDay(today, offset)
    const iso = toISO(d)
    days.push({
      iso,
      code: WEEKDAY_RU[d.getDay()],
      num: d.getDate(),
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
  }, [selected])

  const scheduledSet = new Set(habitDays)

  return (
    <div
      ref={scrollerRef}
      className="week-strip no-scrollbar flex justify-start items-end gap-1.5 mt-5 select-none overflow-x-auto"
    >
      {days.map(({ iso, code, num, isSelected }) => {
        if (isSelected) {
          return (
            <button
              key={iso}
              type="button"
              data-selected="true"
              onClick={() => onSelect?.(iso)}
              aria-label={`${code}, ${num}`}
              className="today-card flex-shrink-0 flex flex-col items-center justify-between w-16 h-[6.5rem] rounded-[26px] bg-[#6d63f0] py-3 shadow-lg shadow-indigo-500/25"
            >
              <span className="text-[13px] font-extrabold text-white">{code}</span>
              <ProgressRing
                size={40}
                stroke={3}
                trackColor="rgba(255,255,255,0.3)"
                color="#ffffff"
                value={activePct}
              >
                <span className="w-9 h-9 rounded-full bg-white flex items-center justify-center">
                  <span className="text-[15px] font-extrabold text-[#232342]">{num}</span>
                </span>
              </ProgressRing>
            </button>
          )
        }

        const scheduled = scheduledSet.has(code)

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
