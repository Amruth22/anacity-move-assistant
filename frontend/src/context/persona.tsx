import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import type { Persona } from '../types'

interface PersonaCtx {
  persona: Persona | null
  setPersona: (p: Persona | null) => void
}

const Ctx = createContext<PersonaCtx>({ persona: null, setPersona: () => {} })

export function PersonaProvider({ children }: { children: ReactNode }) {
  const [persona, setPersonaState] = useState<Persona | null>(() => {
    const raw = sessionStorage.getItem('persona')
    return raw ? JSON.parse(raw) : null
  })

  useEffect(() => {
    if (persona) sessionStorage.setItem('persona', JSON.stringify(persona))
    else sessionStorage.removeItem('persona')
  }, [persona])

  return <Ctx.Provider value={{ persona, setPersona: setPersonaState }}>{children}</Ctx.Provider>
}

export const usePersona = () => useContext(Ctx)
