const MyInput = ({ value, onChange, placeholder }) => (
  <input 
    type="text"
    value={value}
    onChange={(e) => onChange(e.target.value)}
    placeholder={placeholder}
    className="border border-gray-300 rounded-lg px-4 py-2 focus:ring-2 focus:ring-blue-500 outline-none w-full max-w-xs"
  />
);

export default MyInput;
