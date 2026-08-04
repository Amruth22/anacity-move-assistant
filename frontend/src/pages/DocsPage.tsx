import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import mermaid from 'mermaid'
import { api } from '../api/client'

mermaid.initialize({
  startOnLoad: false,
  theme: 'base',
  themeVariables: {
    background: '#fffdf8',
    primaryColor: '#e3ece6',
    primaryTextColor: '#1c2420',
    primaryBorderColor: '#14513f',
    lineColor: '#4b564f',
    fontFamily: "'Instrument Sans', sans-serif",
  },
})

let diagramSeq = 0

/** Renders one fenced mermaid block as an actual diagram. */
function Diagram({ code }: { code: string }) {
  const host = useRef<HTMLDivElement>(null)

  useEffect(() => {
    let live = true
    const id = `docs-diagram-${diagramSeq++}`
    mermaid
      .render(id, code)
      .then(({ svg }) => {
        if (live && host.current) host.current.innerHTML = svg
      })
      .catch(() => {
        // a diagram that will not parse should not take the page down with it
        if (live && host.current) host.current.textContent = code
      })
    return () => {
      live = false
    }
  }, [code])

  return <div className="diagram" ref={host} />
}

export default function DocsPage() {
  const [content, setContent] = useState('')

  useEffect(() => {
    api.docsContent().then(setContent)
  }, [])

  return (
    <div className="docs-body">
      <ReactMarkdown
        components={{
          // a diagram brings its own surface, so it should not sit in a code slab
          pre({ children, ...props }) {
            const first = Array.isArray(children) ? children[0] : children
            const cls = (first as { props?: { className?: string } })?.props?.className
            if (cls === 'language-mermaid') return <>{children}</>
            return <pre {...props}>{children}</pre>
          },
          code({ className, children, ...props }) {
            const text = String(children)
            if (className === 'language-mermaid') return <Diagram code={text.trim()} />
            return (
              <code className={className} {...props}>
                {children}
              </code>
            )
          },
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  )
}
