import { Home, Users, ShieldCheck } from 'lucide-react';

export const navConfig = [
    { path: '/', label: '首頁', icon: Home, pub: true },
    { 
        path: '/admin/users', 
        label: '使用者管理', 
        icon: Users, 
        pub: false, 
        adminOnly: true 
    },
    { 
        path: '/admin/aliases', 
        label: '別名管理', 
        icon: ShieldCheck, 
        pub: false, 
        adminOnly: true 
    },
];
