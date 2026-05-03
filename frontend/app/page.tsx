'use client';

import dynamic from 'next/dynamic';

import { AgentForm } from '@/components/AgentForm';

const SibylFiPrototype = dynamic(() => import('@/components/SibylFiPrototype'), { ssr: false });

export default function Page() {
  return (
    <>
      <SibylFiPrototype />
      <AgentForm />
    </>
  );
}
