"""手工 DOM 联调，不删除业务、不上传文件、不保存或送审。"""

from pathlib import Path
import json
import re
import sys
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.browser import BrowserConfig, BrowserSession
from src.input_loader import load_input
from src.new_audit_qualification import NewAuditQualificationPage
from src.run_logging import application_data_dir
from src.workflow import WorkflowConfig, WorkflowRunner


class Inspector(WorkflowRunner):
    def _run_industry_qualification(self, page, company):
        view = NewAuditQualificationPage(page, timeout=60_000)
        print('STAGE: detail loaded, opening business form', flush=True)
        try:
            add = view._wait_for_unique_visible(
                page.get_by_role('button', name='新增资质', exact=True),
                '新增资质', timeout=120_000,
            )
            add.click()
            view._wait_until(view._is_new_audit_add_page, '新增页未加载', timeout=60_000)
            if not view._business_tabs():
                view._unique_visible(view._add_business_buttons(), '新增业务资质').click()
            view._wait_until(lambda: bool(view._business_tabs()), '已有业务未加载', timeout=60_000)
        except Exception:
            parsed = urlsplit(page.url)
            print('ENTRY_STATE', {
                'host': parsed.hostname, 'path': parsed.path,
                'route': '/'.join(parsed.fragment.split('/')[:3]),
                'addQualificationButtons': page.get_by_role('button', name='新增资质', exact=True).count(),
                'addBusinessButtons': view._add_business_buttons().count(),
            }, flush=True)
            raise
        # 仅输出结构元数据；禁止输出 input.value、整页 HTML 和动态 URL。
        structure = page.evaluate("""() => {
          const visible = e => !!e.getClientRects().length;
          return [...document.querySelectorAll('*')]
            .filter(e => visible(e) && /^业务\\d+$/.test(e.textContent.trim())
              && ![...e.children].some(c => /^业务\\d+$/.test(c.textContent.trim())))
            .map(e => {
              const ancestors = [];
              for (let p = e; p && ancestors.length < 5; p = p.parentElement) {
                ancestors.push({tag:p.tagName, class:p.className,
                  inputs:[...p.querySelectorAll('input')].slice(0, 6).map(i => ({
                    type:i.type, placeholder:i.getAttribute('placeholder'),
                    role:i.getAttribute('role'), visible:visible(i)
                  }))});
              }
              return {label:e.textContent.trim(), ancestors};
            });
        }""")
        print(json.dumps(structure, ensure_ascii=False), flush=True)
        for index in sorted(view._business_tabs()):
            container = view._business_container(index)
            print(json.dumps({
                'business': index,
                'containerTag': container.evaluate('(e) => e.tagName') if container else None,
                'containerClass': container.get_attribute('class') if container else None,
                'promotionMatch': view._business_type_matches(container, '推广审查') if container else False,
                'visibleUploadCards': [
                    view._upload_container(file_input).evaluate("""card => ({
                      previewCounts: [...card.querySelectorAll('.file-count')]
                        .filter(e => e.getClientRects().length).map(e => e.innerText.trim()),
                      deleteCount: card.querySelectorAll('.delete-btn').length,
                      evidencePresent: [...card.querySelectorAll('input')]
                        .filter(e => e.type !== 'file').some(e => e.value.trim()),
                      saved: [...card.querySelectorAll('*')]
                        .some(e => e.textContent.trim() === '已保存待送审'),
                      cardText: card.innerText.slice(0, 260),
                      timelineText: card.closest('.el-timeline-item')
                        ? card.closest('.el-timeline-item').innerText.slice(0, 320) : '',
                    })""")
                    for file_input in view._file_inputs_in(container)
                ] if container else [],
            }, ensure_ascii=False), flush=True)
        for index in sorted(view._business_tabs()):
            card = view._business_container(index)
            print('CARD', card.evaluate("""e => ({
              business:[...e.querySelectorAll('*')].filter(x =>
                x.textContent.trim() === '经营业务').map(x => ({
                  tag:x.tagName, class:x.className,
                  parentTag:x.parentElement && x.parentElement.tagName,
                  parentClass:x.parentElement && x.parentElement.className,
                  parentText:x.parentElement && x.parentElement.innerText.slice(0,180)
                })),
              deletes:[...e.querySelectorAll('*')].filter(x =>
                x.textContent.trim() === '删除' && x.getClientRects().length).map(x => ({
                  tag:x.tagName, class:x.className, role:x.getAttribute('role')
                }))
            })"""), flush=True)
        before = set(view._business_tabs())
        view._unique_visible(view._add_business_buttons(), '新增业务资质').click()
        view._wait_until(
            lambda: len(set(view._business_tabs()) - before) == 1,
            '诊断空白业务卡未出现',
        )
        blank_index = next(iter(set(view._business_tabs()) - before))
        view._click_business_tab(blank_index)
        blank = view._business_container(blank_index)
        search = view._visible(view._business_query_inputs(blank))[-1]
        for qualification_type in company.qualification_types:
            search.click()
            search.fill(qualification_type.type_name)
            page.wait_for_timeout(1_000)
            options = page.locator('[role=option]').evaluate_all("""options => options
              .filter(option => option.getClientRects().length)
              .map(option => ({
                text: option.innerText.trim(),
                ariaDisabled: option.getAttribute('aria-disabled'),
                className: String(option.className || ''),
                nativeDisabled: Boolean(option.disabled),
              }))""")
            print('OPTION_STATE', {
                'query': qualification_type.type_name,
                'options': options,
            }, flush=True)
            page.keyboard.press('Escape')
            search.fill('')
        return False, False, None


def main():
    companies = load_input(Path('input'))
    if len(companies) != 1:
        raise RuntimeError('诊断仅支持输入中恰好一家公司')
    config = BrowserConfig(
        auth_state_path=application_data_dir() / 'auth' / 'storage_state.json',
    )
    with BrowserSession(config) as session:
        session.context.route(
            re.compile(r'/permit/web/permit/(?:submitlice|submitall)(?:[?#]|$)'),
            lambda route: route.abort(),
        )
        print('STAGE: navigating qualification pages', flush=True)
        Inspector(session, WorkflowConfig(final_submit=False, page_timeout_ms=60_000)).run_company(companies[0])
    print('DOM inspection completed; no uploads or final submission.')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        # Playwright 异常可能附带含动态凭证的 URL，不输出原始异常。
        print(f'DOM inspection stopped: {type(exc).__name__}', flush=True)
        sys.exit(1)
