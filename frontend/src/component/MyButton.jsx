const MyButton = ({ children, onClick }) => (
  <button 
    onClick={onClick}
    className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition-all active:scale-95"
  >
    {children}
  </button>
);

export default MyButton;
