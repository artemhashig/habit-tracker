import React, { useState, useEffect } from 'react';
import {
  List, SlidersHorizontal, Plus, ChevronDown, ChevronUp,
  Brain, Dumbbell, Languages, Activity, Eye, BarChart2, Users, Settings
} from 'lucide-react';
import './App.css';

const API_URL = import.meta.env.PROD
  ? 'https://habit-tracker-artem443.amvera.io'
  : 'http://127.0.0.1:8000';

export default function App() {
  const [habits, setHabits] = useState([]);
  const [openCategories, setOpenCategories] = useState({ 'Саморазвитие': true, 'Спорт': true });

  useEffect(() => {
    fetch(`${API_URL}/api/habits`)
      .then(res => res.json())
      .then(data => setHabits(data))
      .catch(err => console.error(err));
  }, []);

  const toggleCategory = (cat) => {
    setOpenCategories(prev => ({ ...prev, [cat]: !prev[cat] }));
  };

  const handleIncrement = (id) => {
    fetch(`${API_URL}/api/habits/${id}/increment`, { method: 'POST' })
      .then(res => res.json())
      .then(updatedHabit => {
        setHabits(prev => prev.map(h => h.id === id ? updatedHabit : h));
      });
  };

  const categories = [...new Set(habits.map(h => h.category))];

  return (
    <div className="app-container">
      {/* Остальной код JSX без изменений */}
      <header className="header">
        <div className="header-left">
          <button className="icon-btn"><List size={18} /></button>
          <button className="icon-btn"><SlidersHorizontal size={18} /></button>
        </div>
        <div className="current-date">3 сент.</div>
        <button className="add-habit-btn"><Plus size={22} /></button>
      </header>

      <main className="content">
        {categories.map(category => (
          <div className="category-container" key={category}>
            <div className="category-header" onClick={() => toggleCategory(category)}>
              <div className="category-title">
                {category === 'Саморазвитие' ? <Brain size={20} /> : <Dumbbell size={20} />}
                {category}
              </div>
              {openCategories[category] ? <ChevronUp size={18} /> : <ChevronDown size={18} />}
            </div>

            {openCategories[category] && (
              <div className="category-habits">
                {habits.filter(h => h.category === category).map(habit => (
                  <div className={`habit-card ${habit.color}`} key={habit.id}>
                    <div className="habit-info">
                      {habit.title.includes('Абхазский') ? <Languages size={20} /> : <Activity size={20} />}
                      <div className="habit-details">
                        <span className="habit-name">{habit.title}</span>
                        <span className="habit-desc">{habit.schedule}</span>
                      </div>
                    </div>
                    <button className="check-btn" onClick={() => handleIncrement(habit.id)}>
                      <Plus size={18} />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
      </main>

      <nav className="tabbar">
        <div className="tab-item active"><Eye size={22} /><span>Привычки</span></div>
        <div className="tab-item"><BarChart2 size={22} /><span>Статистика</span></div>
        <div className="tab-item"><Users size={22} /><span>Общий доступ</span></div>
        <div className="tab-item"><Settings size={22} /><span>Настройки</span></div>
      </nav>
    </div>
  );
}