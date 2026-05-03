'use client';

import dynamic from 'next/dynamic';

import { Web3Provider } from '@/components/Web3Provider';

const SibylFiPrototype = dynamic(() => import('@/components/SibylFiPrototype'), { ssr: false });

export default function Page() {
  return (
    <Web3Provider>
      <SibylFiPrototype />
    </Web3Provider>
  );
}
