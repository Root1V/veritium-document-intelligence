import { createContext, useContext } from 'react'

export const AssistantContext = createContext<{ openFor: (caseId: string) => void }>({ openFor: () => {} })

/** Opens the floating assistant on a case, from that case's page. */
export const useAssistant = () => useContext(AssistantContext)
