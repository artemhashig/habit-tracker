/**
 * Кольцо прогресса: дуговой индикатор 0…1 (трек + закрывающаяся дуга).
 * Используется в ленте дней (кольцо дня), карточках привычек (кольцо вокруг «+»)
 * и в шапках категорий (кольцо сворачивания).
 */
export default function ProgressRing({
  size = 40,
  stroke = 3,
  trackColor = 'rgba(255,255,255,0.2)',
  color = '#ffffff',
  value = 0,
  className = '',
  children,
}) {
  const r = (size - stroke) / 2
  const circ = 2 * Math.PI * r
  const v = Math.max(0, Math.min(1, value))
  return (
    <div
      className={`relative flex items-center justify-center flex-shrink-0 ${className}`}
      style={{ width: size, height: size }}
    >
      <svg viewBox={`0 0 ${size} ${size}`} className="absolute inset-0 -rotate-90">
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke={trackColor}
          strokeWidth={stroke}
        />
        {v > 0 && (
          <circle
            cx={size / 2}
            cy={size / 2}
            r={r}
            fill="none"
            stroke={color}
            strokeWidth={stroke}
            strokeLinecap="round"
            strokeDasharray={`${v * circ} ${circ}`}
          />
        )}
      </svg>
      {children}
    </div>
  )
}
