import type { ReactNode } from 'react'

/** 统一页头：标题 + 一句话说明 + 右侧动作区，所有业务页共用，保证观感一致 */
export default function PageHeader({ title, description, extra }: {
  title: string
  description?: string
  extra?: ReactNode
}) {
  return (
    <div className="page-header">
      <div className="page-header-text">
        <h2 className="page-title">{title}</h2>
        {description && <p className="page-desc">{description}</p>}
      </div>
      {extra && <div className="page-extra">{extra}</div>}
    </div>
  )
}
