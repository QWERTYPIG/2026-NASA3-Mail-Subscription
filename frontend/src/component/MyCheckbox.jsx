// src/component/MyCheckbox.js
import React from 'react';

const MyCheckbox = ({ label, checked, onChange, id }) => {
  return (
    <div className="flex items-center gap-3 cursor-pointer group">
      <div className="relative flex items-center">
        <input
          id={id}
          type="checkbox"
          checked={checked}
          onChange={(e) => onChange(e.target.checked)}
          className="peer h-5 w-5 cursor-pointer appearance-none rounded border border-emerald-300 bg-white checked:bg-emerald-500 checked:border-emerald-500 transition-all"
        />
        {/* Checkmark Icon - 只有在選取時顯示 */}
        <svg
          className="absolute h-3.5 w-3.5 pointer-events-none hidden peer-checked:block stroke-white mt-0.5 ml-0.5"
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="4"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <polyline points="20 6 9 17 4 12"></polyline>
        </svg>
      </div>
      {label && (
        <label htmlFor={id} className="text-sm font-medium text-gray-700 cursor-pointer group-hover:text-emerald-600 transition-colors">
          {label}
        </label>
      )}
    </div>
  );
};

export default MyCheckbox;
