const WEEKDAY_RU = ['Вс', 'Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб']

// длина окружности кольца (r = 18)
const RING_CIRC = 2 * Math.PI * 18

function shiftDay(base, offset) {
  const d = new Date(base)
  d.setDate(d.getDate() + offset)
  return d
}

/**
 * Лента «неделя»: 6 дней до сегодня + завтра.
 * activePct — доля закрытых на сегодня привычек (кольцо прогресса).
 * habitDays — дни недели, на которые хоть что-то запланировано.
 */
export default function WeekStrip({ activePct = 0, habitDays = [] }) {
  const today = new Date()
  const days = []

  for (let offset = -5; offset <= 1; offset++) {
    const d = shiftDay(today, offset)
    days.push({
      code: WEEKDAY_RU[d.getDay()],
      num: d.getDate(),
      isToday: offset === 0,
    })
  }

  const scheduledSet = new Set(habitDays)

  return (
    <div className="flex justify-between items-end px-0.5 mt-5 select-none">
      {days.map(({ code, num, isToday }, i) => {
        if (isToday) {
          return (
            <div
              key={i}
              className="flex flex-col items-center justify-between w-[4.5rem] h-[6.75rem] rounded-[30px] bg-[#6d63f0] py-3 shadow-lg shadow-indigo-500/25"
            >
              <span className="text-[13px] font-extrabold text-white">{code}</span>
              <div className="relative w-10 h-10 flex items-center justify-center">
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
                    stroke="#ffffff"
                    strokeWidth="3"
                    strokeLinecap="round"
                    strokeDasharray={`${activePct * RING_CIRC} ${RING_CIRC}`}
                  />
                </svg>
                <span className="text-[16px] font-extrabold text-[#232342]">{num}</span>
              </div>
            </div>
          )
        }

        const scheduled = scheduledSet.has(code)
        if (scheduled) {
          return (
            <div key={i} className="flex flex-col items-center gap-1 w-11">
              <span className="text-[13px] font-bold text-white/60">{code}</span>
              <div className="w-10 h-10 rounded-full bg-[#181928] border border-[#272848] flex items-center justify-center">
                <span className="text-[15px] font-extrabold text-white">{num}</span>
              </div>
            </div>
          )
        }

        return (
          <div key={i} className="flex flex-col items-center gap-1 w-11">
            <span className="text-[13px] font-bold text-white/35">{code}</span>
            <span className="h-10 flex items-center text-[15px] font-extrabold text-white/60">
              {num}
            </span>
          </div>
        )
      })}
    </div>
  )
}
