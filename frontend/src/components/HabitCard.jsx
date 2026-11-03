import { Check, Plus } from 'lucide-react'
import ProgressRing from './ProgressRing.jsx'
import useLongPress from './useLongPress.js'

/**
 * Карточка привычки (по макету): база тёмная, цвет слева направо закрашивает
 * карточку пропорционально прогрессу дня (current/target).
 * Кнопка «+» — кольцо, заполняющееся тем же прогрессом; после закрытия
 * «+» превращается в галочку (белый кружок — без кольца-обводки).
 * Удержание карточки → onLongPress (окно удаления).
 * disabled — день в будущем (завтра и позже): просматривать можно, отмечать нельзя.
 */
export default function HabitCard({ habit, onIncrement, onLongPress, disabled = false }) {
  const done = habit.status === 'done'
  const frozen = Boolean(habit.frozen)
  const scheduled = Boolean(habit.scheduledToday) || habit.current > 0
  const pct = habit.target > 0 ? Math.min(1, (habit.current || 0) / habit.target) : 0
  const longPress = useLongPress(() => onLongPress?.())

  // --- Пауза: нейтральная серая, без действий ---
  if (frozen) {
    return (
      <div {...longPress} className="rise no-callout select-none rounded-[22px] bg-[#1b1b26] border border-[#2b2b3c] p-4 flex items-center gap-3">
        <div className="flex-1 min-w-0 flex flex-col gap-0.5">
          <span className="text-[17px] font-extrabold text-white leading-tight truncate">
            {habit.title}
          </span>
          <span className="text-[13px] font-semibold text-white/45">{habit.scheduleText}</span>
        </div>
      </div>
    )
  }

  const base = scheduled ? '#2b2510' : '#1b1b26'
  const border = scheduled ? 'transparent' : '#2b2b3c'
  const fill = scheduled ? '#d4a20d' : '#31314a' // закрашивается слева направо
  const accent = scheduled ? 'text-[#d4a20d]' : 'text-[#8f85ff]'

  return (
    <div
      {...longPress}
      className="rise no-callout select-none relative overflow-hidden rounded-[22px]"
      style={{ background: base, border: `1px solid ${border}` }}
    >
      {/* заливка прогресса: от нуля (пустая база) до полного дня */}
      {scheduled && pct > 0 && (
        <div
          className="absolute inset-y-0 left-0 transition-all duration-200"
          style={{ width: `${pct * 100}%`, background: fill, borderRadius: '22px' }}
        />
      )}

      <div className="relative flex flex-col gap-1 py-4 pl-4 pr-[4.75rem]">
        <div className="flex items-center gap-2">
          {habit.deficit > 0 && !done && (
            <span className="text-[13px] font-extrabold text-white bg-[#b3261e] rounded-md px-1.5 flex-shrink-0">
              −{habit.deficit}
            </span>
          )}
          <span className={`flex-1 min-w-0 text-[17px] font-extrabold leading-tight truncate ${scheduled || done ? 'text-white' : 'text-white/90'}`}>
            {habit.title}
          </span>
        </div>
        <span className={`text-[13px] font-semibold ${scheduled || done ? 'text-white/90' : 'text-white/45'}`}>
          {habit.scheduleText}
        </span>
      </div>

      {/* кнопка: кольцо заполняется с привычкой; когда день закрыт — галочка без обводки */}
      <button
        onClick={() => onIncrement?.(habit.id)}
        disabled={disabled}
        aria-label={done ? `Закрыто: «${habit.title}»` : `Добавить к «${habit.title}»`}
        className="absolute right-3 top-1/2 -translate-y-1/2 w-14 h-14 flex items-center justify-center transition-transform active:scale-90 disabled:opacity-40 disabled:active:scale-100"
      >
        {done ? (
          <span className="w-[52px] h-[52px] rounded-full bg-white flex items-center justify-center">
            <Check size={28} strokeWidth={3.2} className={accent} />
          </span>
        ) : (
          <ProgressRing
            size={56}
            stroke={4}
            trackColor="rgba(255,255,255,0.25)"
            color="#ffffff"
            value={pct}
          >
            <span className="w-[42px] h-[42px] rounded-full bg-white flex items-center justify-center">
              <Plus size={24} strokeWidth={2.8} className={accent === 'text-[#d4a20d]' ? 'text-[#d4a20d]' : 'text-[#26263a]'} />
            </span>
          </ProgressRing>
        )}
      </button>
    </div>
  )
}
