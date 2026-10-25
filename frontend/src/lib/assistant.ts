import { createContext, useContext } from 'react'

export const AssistantContext = createContext<{ open: boolean; openFor: (caseId: string) => void }>({ open: false, openFor: () => {} })

/** The floating assistant: whether its panel is open, and opening it on a case from that case's page. */
export const useAssistant = () => useContext(AssistantContext)
