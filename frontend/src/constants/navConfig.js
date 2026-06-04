import { Home, Users, ShieldCheck } from 'lucide-react';

export const navConfig = [
    { path: '/', label: '首頁', icon: Home, pub: false },
    { 
        path: '/manage/aliases', 
        label: '別名管理', 
        icon: ShieldCheck, 
        pub: false, 
        adminOnly: true 
    },
];
