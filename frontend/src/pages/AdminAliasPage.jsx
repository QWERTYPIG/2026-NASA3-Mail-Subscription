import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import api from '../api/axios';
import { toast } from 'react-hot-toast';
import { ShieldCheck, Plus, Settings, Trash2, Loader2, ArrowRight, Mail } from 'lucide-react';

const AdminAliasPage = () => {
  const [aliases, setAliases] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);
  const [newAlias, setNewAlias] = useState({ name: '', description: '' });

  const fetchAliases = async () => {
    try {
      const res = await api.get('/admin/aliases');
      setAliases(res.data);
    } catch {
      toast.error("無法取得別名清單");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchAliases(); }, []);

  const handleCreate = async (e) => {
    e.preventDefault();
    try {
      await api.post('/admin/aliases', newAlias);
      toast.success("別名建立成功");
      setShowModal(false);
      setNewAlias({ name: '', description: '' });
      fetchAliases();
    } catch {
      toast.error("建立失敗，名稱可能已存在");
    }
  };

  if (loading) return <div className="flex justify-center p-20"><Loader2 className="animate-spin text-indigo-600" size={40} /></div>;

  return (
    <div className="max-w-5xl mx-auto">
      <div className="flex justify-between items-center mb-8">
        <div>
          <h1 className="text-2xl font-bold text-slate-800 flex items-center gap-2">
            <ShieldCheck className="text-indigo-600" /> 別名系統管理
          </h1>
          <p className="text-slate-500">管理郵件群組、查看訂閱成員與別名設定。</p>
        </div>
        <button 
          onClick={() => setShowModal(true)}
          className="bg-indigo-600 text-white px-4 py-2 rounded-lg font-bold hover:bg-indigo-700 flex items-center gap-2 transition-all shadow-md"
        >
          <Plus size={18} /> 新增別名
        </button>
      </div>

      <div className="grid gap-4">
        {aliases.map(alias => (
          <div key={alias.id} className="bg-white border border-slate-200 rounded-xl p-5 flex items-center justify-between hover:shadow-md transition-shadow">
            <div className="flex items-center gap-4">
              <div className="bg-indigo-50 p-3 rounded-full text-indigo-600">
                <Mail size={24} />
              </div>
              <div>
                <h3 className="font-bold text-slate-800 text-lg uppercase tracking-wide">{alias.name}</h3>
                <p className="text-slate-500 text-sm">{alias.description || "暫無描述"}</p>
              </div>
            </div>

            <div className="flex items-center gap-2">
              <Link 
                to={`/admin/alias/${alias.id}`}
                className="flex items-center gap-2 px-4 py-2 bg-slate-100 text-slate-700 font-semibold rounded-lg hover:bg-indigo-600 hover:text-white transition-all"
              >
                <Settings size={16} />
                <span>管理成員</span>
                <ArrowRight size={16} />
              </Link>
            </div>
          </div>
        ))}
      </div>

      {/* 新增別名 Modal */}
      {showModal && (
        <div className="fixed inset-0 bg-slate-900/50 backdrop-blur-sm flex items-center justify-center z-[100]">
          <form onSubmit={handleCreate} className="bg-white rounded-2xl shadow-2xl w-full max-w-md p-6 space-y-4 animate-in zoom-in-95 duration-200">
            <h2 className="text-xl font-bold text-slate-800">建立新郵件別名</h2>
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1">別名名稱 (例如: security-alerts)</label>
              <input 
                required
                className="w-full p-2.5 border rounded-lg focus:ring-2 focus:ring-indigo-500 outline-none"
                value={newAlias.name}
                onChange={e => setNewAlias({...newAlias, name: e.target.value})}
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1">描述</label>
              <textarea 
                className="w-full p-2.5 border rounded-lg focus:ring-2 focus:ring-indigo-500 outline-none"
                value={newAlias.description}
                onChange={e => setNewAlias({...newAlias, description: e.target.value})}
              />
            </div>
            <div className="flex gap-3 pt-2">
              <button type="button" onClick={() => setShowModal(false)} className="flex-1 py-2 border rounded-lg font-bold text-slate-600">取消</button>
              <button type="submit" className="flex-1 py-2 bg-indigo-600 text-white rounded-lg font-bold hover:bg-indigo-700">確認建立</button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}

export default AdminAliasPage;
