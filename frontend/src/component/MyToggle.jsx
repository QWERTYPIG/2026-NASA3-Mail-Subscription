// src/component/MyToggle.js
import React from 'react';

const MyToggle = ({ label, enabled, setEnabled }) => {
  return (
    <div className="flex items-center justify-between gap-4 py-2">
      {label && <span className="text-sm font-medium text-gray-700">{label}</span>}
      <button
        onClick={() => setEnabled(!enabled)}
        className={`${
          enabled ? 'bg-emerald-500' : 'bg-gray-200'
        } relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:ring-offset-2`}
      >
        <span
          className={`${
            enabled ? 'translate-x-6' : 'translate-x-1'
          } inline-block h-4 w-4 transform rounded-full bg-white transition-transform`}
        />
      </button>
    </div>
  );
};

export default MyToggle;
