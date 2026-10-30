import { useState } from 'react'
import { X } from 'lucide-react'
import api from '../api.js'

// популярные единицы для быстрого ввода плана
const UNIT_SUGGESTIONS = ['раз', 'минута', 'страница', 'стакан', 'километр', 'повторение']

/**
 * Экран «Новая привычка» — минимальные настройки:
 *   • категория: выбрать существующую чипом или вписать новую
 *   • название привычки
 *   • план: за сколько (число + единица) закрывается день
 * Дальше всё по умолчанию: график — каждый день, эмодзи — ✨.
 */
export default function CreateHabitScreen({
  categories = [],
  onClose,
  onCreated,
  onError,
}) {
  const [title, setTitle] = useState('')
  const [category, setCategory] = useState(categories[0] || 'Другое')
  const [newCategory, setNewCategory] = useState('') // значение при вводе новой
  const [target, setTarget] = useState('1')
  const [unit, setUnit] = useState('раз')
  const [busy, setBusy] = useState(false)

  const isCustomCategory = !categories.includes(category)

  const setExistingCategory = (name) => {
    setCategory(name)
    setNewCategory('')
  }

  const submit = async (e) => {
    e.preventDefault()
    if (busy) return
    const name = title.trim()
    if (!name) return
    const finalCategory = (isCustomCategory ? newCategory.trim() : category) || 'Другое'
    setBusy(true)
    try {
      const r = await api('/api/habits', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: name,
          category: finalCategory,
          target: Math.max(1, parseInt(target || '1', 10) || 1),
          unit: unit.trim() || 'раз',
        }),
      })
      const data = await r.json()
      if (!r.ok) throw new Error(data.detail || 'Не удалось создать привычку')
      onCreated?.(data)
    } catch (err) {
      onError?.(err.message || 'Ошибка сети')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 bg-[#050508] flex justify-center">
      <div className="w-full max-w-md flex flex-col h-full">
        {/* Шапка */}
        <header className="flex items-center gap-3 px-4 pt-4 pb-3">
          <div className="w-11 h-11 rounded-full bg-[#1a1a25] flex items-center justify-center flex-shrink-0">
            <span className="text-[20px]">✨</span>
          </div>
          <div className="flex-1 min-w-0">
            <h2 className="text-[19px] font-extrabold text-white leading-tight">
              Новая привычка
            </h2>
            <p className="text-[12px] text-white/45 truncate">
              дальше я сам всё подстрою в чате
            </p>
          </div>
          <button
            onClick={onClose}
            aria-label="Закрыть"
            className="w-11 h-11 rounded-full bg-[#1a1a25] flex items-center justify-center text-white/80 hover:text-white transition active:scale-90"
          >
            <X size={20} />
          </button>
        </header>

        <form onSubmit={submit} className="flex-1 overflow-y-auto px-4 pb-4 flex flex-col gap-5">
          {/* Категория */}
          <section className="flex flex-col gap-2.5">
            <h3 className="text-[13px] font-extrabold text-white/50 uppercase tracking-wide px-1">
              Категория
            </h3>
            <div className="flex flex-wrap gap-2">
              {categories.map((c) => (
                <button
                  type="button"
                  key={c}
                  onClick={() => setExistingCategory(c)}
                  className={`px-3.5 py-2 rounded-full text-[14px] font-bold border transition ${
                    !isCustomCategory && c === category
                      ? 'bg-[#6d63f0] border-[#6d63f0] text-white'
                      : 'bg-[#17171f] border-white/10 text-white/70 hover:bg-[#21212c]'
                  }`}
                >
                  {c}
                </button>
              ))}
              <button
                type="button"
                onClick={() => setCategory('')}
                aria-label="Новая категория"
                className={`px-3.5 py-2 rounded-full text-[14px] font-bold border transition ${
                  isCustomCategory
                    ? 'bg-[#6d63f0] border-[#6d63f0] text-white'
                    : 'bg-[#17171f] border-white/10 text-white/70 hover:bg-[#21212c]'
                }`}
              >
                + Новая
              </button>
            </div>
            {isCustomCategory && (
              <input
                autoFocus
                value={newCategory}
                onChange={(e) => setNewCategory(e.target.value)}
                placeholder="Название новой категории"
                maxLength={60}
                className="bg-[#17171f] rounded-2xl px-4 py-3 text-[15px] font-semibold text-white placeholder-white/30 outline-none focus:ring-2 ring-[#6d63f0]/40"
              />
            )}
          </section>

          {/* Название */}
          <section className="flex flex-col gap-2.5">
            <h3 className="text-[13px] font-extrabold text-white/50 uppercase tracking-wide px-1">
              Привычка
            </h3>
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Например: Зарядка"
              maxLength={120}
              className="bg-[#17171f] rounded-2xl px-4 py-3.5 text-[16px] font-bold text-white placeholder-white/30 outline-none focus:ring-2 ring-[#6d63f0]/40"
            />
          </section>

          {/* План на день */}
          <section className="flex flex-col gap-2.5">
            <h3 className="text-[13px] font-extrabold text-white/50 uppercase tracking-wide px-1">
              За сколько закрывается день
            </h3>
            <div className="flex gap-2.5">
              <input
                type="number"
                inputMode="numeric"
                min="1"
                value={target}
                onChange={(e) => setTarget(e.target.value)}
                className="w-24 bg-[#17171f] rounded-2xl px-4 py-3 text-[16px] font-bold text-white text-center outline-none focus:ring-2 ring-[#6d63f0]/40"
                aria-label="Количество"
              />
              <input
                value={unit}
                onChange={(e) => setUnit(e.target.value)}
                placeholder="единица"
                list="unit-suggestions"
                maxLength={40}
                className="flex-1 bg-[#17171f] rounded-2xl px-4 py-3 text-[15px] font-semibold text-white placeholder-white/30 outline-none focus:ring-2 ring-[#6d63f0]/40"
                aria-label="Единица"
              />
              <datalist id="unit-suggestions">
                {UNIT_SUGGESTIONS.map((u) => (
                  <option key={u} value={u} />
                ))}
              </datalist>
            </div>
            <p className="text-[12px] text-white/35 px-1">
              например: 20 · минута &nbsp;|&nbsp; 1 · раз &nbsp;|&nbsp; 10 · страница
            </p>
          </section>

          {/* Кнопка создать */}
          <button
            type="submit"
            disabled={busy || !title.trim() || (isCustomCategory && !newCategory.trim())}
            className="mt-2 w-full rounded-full bg-[#6d63f0] disabled:bg-[#26263a] disabled:text-white/30 py-3.5 text-[16px] font-extrabold text-white transition active:scale-[0.98] flex items-center justify-center gap-2"
          >
            {busy ? 'Создаю…' : 'Создать привычку'}
          </button>
        </form>
      </div>
    </div>
  )
}
