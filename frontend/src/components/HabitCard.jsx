import { Check, Plus, Flame } from 'lucide-react'
import useLongPress from './useLongPress.js'

const MINUS = '\u2212' // типографский минус как на макете

/**
 * Карточка привычки.
 *  - status 'done'   → зелёная, кнопка-галочка, бейдж серии 🔥
 *  - scheduledToday  → жёлтая («отстаём»), бейдж −N, кнопка «+»
 *  - иначе           → нейтральная серая (привычка по другому графику)
 *  Удержание карточки → onLongPress (окно удаления).
 */
export default function HabitCard({ habit, onIncrement, onLongPress }) {
  const done = habit.status === 'done'
  const scheduled = Boolean(habit.scheduledToday) || habit.current > 0
  const longPress = useLongPress(() => onLongPress?.())

  // --- Зелёная: день закрыт ---
  if (done) {
    return (
      <div {...longPress} className="rise no-callout select-none rounded-[22px] bg-[#12c25d] p-4 flex items-start gap-3">
        <div className="w-11 flex flex-col items-center gap-0.5">
          {habit.streak > 0 && (
            <div className="flex items-center gap-0.5">
              <Flame size={15} className="text-[#ffb020] fill-[#ffb020]" />
              <span className="text-[13px] font-extrabold text-white">{habit.streak}</span>
            </div>
          )}
          <span className="text-[26px] leading-none mt-1">{habit.emoji || '✅'}</span>
        </div>

        <div className="flex-1 min-w-0 flex flex-col justify-center gap-0.5 pt-2.5">
          <span className="text-[17px] font-extrabold text-white leading-tight truncate">
            {habit.title}
          </span>
          <span className="text-[13px] font-semibold text-white/85">{habit.daysLabel}</span>
        </div>

        <button
          onClick={() => onIncrement?.(habit.id)}
          className="mt-1 w-14 h-14 rounded-full bg-white flex items-center justify-center flex-shrink-0 text-[#12c25d] transition-transform active:scale-90"
          aria-label={`Отметить «${habit.title}»`}
        >
          <Check size={26} strokeWidth={3} />
        </button>
      </div>
    )
  }

  // --- Жёлтая: запланировано на сегодня, но отстаём ---
  if (scheduled) {
    return (
      <div {...longPress} className="rise no-callout select-none rounded-[22px] bg-[#3e3712] p-4 flex items-start gap-3">
        <div className="w-11 flex flex-col items-center gap-0.5">
          {habit.deficit > 0 && (
            <span className="text-[13px] font-extrabold text-[#ff5148]">
              {MINUS}
              {habit.deficit}
            </span>
          )}
          <span className="text-[26px] leading-none mt-1">{habit.emoji || '🎯'}</span>
        </div>

        <div className="flex-1 min-w-0 flex flex-col justify-center gap-0.5 pt-2.5">
          <span className="text-[17px] font-extrabold text-white leading-tight">
            {habit.title}
          </span>
          <span className="text-[13px] font-semibold text-[#d8d5bd]/80">
            {habit.scheduleText}
          </span>
        </div>

        <button
          onClick={() => onIncrement?.(habit.id)}
          className="mt-1 w-14 h-14 rounded-full bg-[#4c4416] border border-[#6b6124] flex items-center justify-center flex-shrink-0 text-white transition-transform active:scale-90"
          aria-label={`Добавить к «${habit.title}»`}
        >
          <Plus size={26} strokeWidth={2.5} />
        </button>
      </div>
    )
  }

  // --- Нейтральная: привычка по другому графику ---
  return (
    <div {...longPress} className="rise no-callout select-none rounded-[22px] bg-[#1b1b26] border border-[#2b2b3c] p-4 flex items-center gap-3">
      <span className="w-11 text-center text-[26px] leading-none">{habit.emoji || '🗓'}</span>

      <div className="flex-1 min-w-0 flex flex-col gap-0.5">
        <span className="text-[17px] font-extrabold text-white leading-tight truncate">
          {habit.title}
        </span>
        <span className="text-[13px] font-semibold text-white/45">{habit.scheduleText}</span>
      </div>

      <button
        onClick={() => onIncrement?.(habit.id)}
        className="w-14 h-14 rounded-full bg-[#262639] border border-[#35354d] flex items-center justify-center flex-shrink-0 text-white/80 transition-transform active:scale-90"
        aria-label={`Отметить «${habit.title}»`}
      >
        <Plus size={26} strokeWidth={2.5} />
      </button>
    </div>
  )
}
