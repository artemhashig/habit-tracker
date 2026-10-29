import { useRef } from 'react'

/**
 * Удержание пальца/мыши ~550 мс → onLongPress().
 *
 * Детали:
 *  • нажатие, начавшееся на <button>, игнорируется — кнопки сами кликабельны;
 *  • сдвиг больше ~12px отменяет (это скролл, не удержание);
 *  • контекстное меню системы по удержанию подавляется (onContextMenu).
 */
export default function useLongPress(onLongPress, ms = 550) {
  const cbRef = useRef(onLongPress)
  cbRef.current = onLongPress
  const timer = useRef(null)

  const onPointerDown = (e) => {
    if (timer.current) return
    if (e.target?.closest?.('button')) return
    if (e.pointerType === 'mouse' && e.button !== 0) return
    e.stopPropagation() // ближайший получатель решает судьбу нажатия

    const sx = e.clientX
    const sy = e.clientY
    const finish = (fire) => {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
      window.removeEventListener('pointercancel', onUp)
      clearTimeout(timer.current)
      timer.current = null
      if (fire) {
        navigator.vibrate?.(35) // лёгкая вибрация-отклик, если доступна
        cbRef.current?.()
      }
    }
    const onMove = (ev) => {
      if (Math.abs(ev.clientX - sx) > 12 || Math.abs(ev.clientY - sy) > 12) finish(false)
    }
    const onUp = () => finish(false)

    timer.current = setTimeout(() => finish(true), ms)
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
    window.addEventListener('pointercancel', onUp)
  }

  return {
    onPointerDown,
    onContextMenu: (e) => e.preventDefault(),
  }
}
