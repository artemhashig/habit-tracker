import React, { useState, useEffect } from 'react';
import { Menu, List, Plus, ChevronUp, Check, Crown } from 'lucide-react';

export default function App() {
  const [habits, setHabits] = useState([]);

  // Имитация календаря для визуала (как на макете)
  const days = [
    { day: 'Сб', date: 19 }, { day: 'Вс', date: 20 },
    { day: 'Пн', date: 21 }, { day: 'Вт', date: 22 },
    { day: 'Ср', date: 23 }, { day: 'Чт', date: 24, active: true },
    { day: 'Пт', date: 25 },
  ];

  // Загрузка данных с твоего FastAPI
  useEffect(() => {
    fetch('/api/habits')
      .then(res => res.json())
      .then(data => setHabits(data))
      .catch(err => console.error("Ошибка загрузки:", err));
  }, []);

  // Функция клика по привычке (интерактив для презентации)
  const handleIncrement = async (id) => {
    try {
      const res = await fetch(`/api/habits/${id}/increment`, { method: 'POST' });
      const updatedHabit = await res.json();

      // Обновляем состояние, чтобы UI изменился мгновенно
      setHabits(habits.map(h => h.id === id ? updatedHabit : h));
    } catch (err) {
      console.error("Ошибка обновления:", err);
    }
  };

  return (
    // Главный контейнер: центрируется на ПК, черный фон
    <div className="min-h-screen bg-[#0a0a0c] text-white flex justify-center font-sans">
      <div className="w-full max-w-md w-full p-4 flex flex-col gap-6">

        {/* Шапка */}
        <header className="flex justify-between items-center mt-2">
          <div className="flex gap-4 bg-[#1a1a24] px-4 py-2 rounded-full">
            <List size={20} className="text-gray-400" />
            <Menu size={20} className="text-gray-400" />
          </div>
          <h1 className="text-lg font-semibold tracking-wide">Сегодня</h1>
          <button className="bg-indigo-500 p-3 rounded-full hover:bg-indigo-600 transition-colors">
            <Plus size={24} />
          </button>
        </header>

        {/* Скроллер дней */}
        <div className="flex justify-between items-center px-1">
          {days.map((item, idx) => (
            <div key={idx} className={`flex flex-col items-center p-2 rounded-full w-12 h-16 justify-center ${item.active ? 'bg-indigo-500' : ''}`}>
              <span className={`text-xs ${item.active ? 'text-white' : 'text-gray-500'}`}>{item.day}</span>
              <span className={`text-sm font-bold ${item.active ? 'text-white' : 'text-gray-300'}`}>{item.date}</span>
            </div>
          ))}
        </div>

        {/* Карточки привычек */}
        <div className="flex flex-col gap-4">

          {/* Категория: Спорт */}
          <div className="border border-red-900/30 bg-[#141419] rounded-3xl p-4 flex flex-col gap-3">
            <div className="flex justify-between items-center text-gray-200 px-2">
              <span className="font-bold flex items-center gap-2">🏋️ Спорт</span>
              <div className="bg-[#2a2a36] p-1 rounded-full"><ChevronUp size={16}/></div>
            </div>

            {habits.filter(h => h.category === 'Спорт').map(habit => (
              <div key={habit.id} className="bg-[#2a2a1a] border border-yellow-900/50 rounded-2xl p-4 flex justify-between items-center">
                <div className="flex flex-col">
                  <span className="text-red-500 font-bold text-sm mb-1">-7</span>
                  <span className="font-bold text-lg">{habit.title}</span>
                  <span className="text-xs text-gray-400">{habit.schedule.replace('0', habit.current)}</span>
                </div>
                <button
                  onClick={() => handleIncrement(habit.id)}
                  className="bg-[#3a3a2a] text-yellow-500 w-12 h-12 rounded-full flex justify-center items-center text-2xl"
                >
                  {habit.current >= habit.total ? <Check size={24} /> : <Plus size={24} />}
                </button>
              </div>
            ))}
          </div>

          {/* Категория: Саморазвитие */}
          <div className="border border-pink-900/30 bg-[#141419] rounded-3xl p-4 flex flex-col gap-3">
            <div className="flex justify-between items-center text-gray-200 px-2">
              <span className="font-bold flex items-center gap-2">🧠 Саморазвитие</span>
              <div className="bg-[#2a2a36] p-1 rounded-full"><ChevronUp size={16}/></div>
            </div>

            {habits.filter(h => h.category === 'Саморазвитие').map(habit => (
              <div key={habit.id} className="bg-green-500 rounded-2xl p-4 flex justify-between items-center">
                <div className="flex items-center gap-3">
                  <div className="bg-white/20 text-white rounded-lg p-2 font-bold w-10 h-10 flex items-center justify-center">A</div>
                  <div className="flex flex-col text-white">
                    <span className="font-bold text-lg">{habit.title}</span>
                    <span className="text-xs text-green-100">{habit.schedule}</span>
                  </div>
                </div>
                <button className="bg-white text-green-500 w-12 h-12 rounded-full flex justify-center items-center shadow-lg">
                  <Check size={24} strokeWidth={3} />
                </button>
              </div>
            ))}
          </div>

          {/* Премиум Баннер */}
          <div className="mt-2 border border-indigo-900/50 bg-[#1a1a2a] rounded-3xl p-4 flex justify-between items-center cursor-pointer">
            <div className="flex items-center gap-3">
              <Crown className="text-yellow-500" size={28} />
              <div className="flex flex-col">
                <span className="text-pink-300 font-bold text-lg">Открыть все</span>
                <span className="text-xs text-gray-400">С Grit Premium</span>
              </div>
            </div>
            <ChevronUp size={20} className="text-gray-500 rotate-90" />
          </div>

          <p className="text-center text-xs text-gray-600 mt-2">Ожидание начала синхронизации...</p>
        </div>

      </div>
    </div>
  );
}