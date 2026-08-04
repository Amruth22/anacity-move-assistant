import { useEffect, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import { api } from '../api/client'

export default function DocsPage() {
  const [content, setContent] = useState('')

  useEffect(() => {
    api.docsContent().then(setContent)
  }, [])

  return (
    <div className="docs-body">
      <ReactMarkdown>{content}</ReactMarkdown>
    </div>
  )
}
