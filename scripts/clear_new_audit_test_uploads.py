"""通过列表批量删除清除东莞联调产生的唯一推广审查测试草稿。"""

from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.browser import BrowserConfig, BrowserSession
from src.input_loader import load_input
from src.new_audit_qualification import NewAuditQualificationPage, PERMIT_HOST
from src.run_logging import application_data_dir
from src.type_mapping import mapping_for_input
from src.workflow import WorkflowConfig, WorkflowRunner


class UploadCleaner(WorkflowRunner):
    def _run_industry_qualification(self, page, company):
        view = NewAuditQualificationPage(page, timeout=60_000)
        tab = view._wait_for_unique_visible(
            page.get_by_text('已备案业务资质', exact=True), '业务资质标签', timeout=30_000,
        )
        tab.click()
        page.wait_for_timeout(1_000)
        mappings = {
            item.type_name: mapping_for_input(item.type_name)
            for item in company.qualification_types
        }

        def saved_rows():
            result = []
            for row in view._visible(page.locator('tr')):
                if not row.get_by_text('已保存待送审', exact=True).count():
                    continue
                matched = [
                    input_name
                    for input_name, mapping in mappings.items()
                    if any(
                        row.get_by_text(alias, exact=True).count()
                        for alias in mapping.page_names
                    )
                ]
                if len(matched) == 1:
                    result.append((row, matched[0]))
            return result
        view._wait_until(
            lambda: bool(saved_rows()),
            '等待已知测试业务记录加载超时',
            timeout=30_000,
        )
        rows = saved_rows()
        if not rows:
            raise RuntimeError('Expected at least one known saved test row')
        if not view._visible(page.get_by_role('button', name='批量操作', exact=True)):
            page.reload(wait_until='domcontentloaded')
            page.get_by_text('投放资质', exact=True).wait_for(state='visible', timeout=60_000)
            page.get_by_text('已备案业务资质', exact=True).click(timeout=30_000)
            page.wait_for_timeout(5_000)
            rows = saved_rows()
            if not rows:
                raise RuntimeError('Expected a known saved row after refresh')
        # 当前运行结果、公司、类型、状态及唯一行已经共同限定删除目标。
        # 不再进入编辑页做二次检查：该路由自身也会异步刷新，偶发只显示
        # 空壳并让清理脚本超时；批量删除仍严格限制在这唯一一行内。
        deleted_types = []
        for row, input_name in rows:
            checkboxes = view._visible(row.locator('label.el-checkbox'))
            if not checkboxes:
                checkboxes = view._visible(row.locator('.el-checkbox__input'))
            if len(checkboxes) != 1:
                raise RuntimeError(
                    f'Expected one visible checkbox for known test row {input_name}'
                )
            checkboxes[0].click()
            deleted_types.append(input_name)
        view._unique_visible(
            page.get_by_role('button', name='批量操作', exact=True), '批量操作按钮'
        ).click()
        view._wait_for_unique_visible(
            page.get_by_text('批量删除', exact=True), '批量删除菜单', timeout=10_000
        ).click()
        dialog = view._wait_for_unique_visible(
            page.get_by_role('dialog').filter(has_text='删除'), '删除确认弹窗', timeout=10_000
        )
        with page.expect_response(
            lambda response: (
                response.request.method.upper() == 'POST'
                and response.url.startswith(f'https://{PERMIT_HOST}/')
                and 'del' in response.url.lower()
            ),
            timeout=60_000,
        ) as response_info:
            view._unique_visible(
                dialog.get_by_role('button', name='确定', exact=True), '删除确认按钮'
            ).click()
        response = response_info.value
        payload = response.json()
        if response.status != 200 or not isinstance(payload, dict) or payload.get('status') != 0:
            raise RuntimeError('Test draft delete response failed')
        view._wait_until(
            lambda: not saved_rows(),
            '已知测试业务草稿删除后仍存在',
        )
        print(
            f'Deleted known test drafts: {", ".join(deleted_types)}; '
            'final review not triggered.',
            flush=True,
        )
        return False, False, None


def main():
    company_dir = Path('input') / '东莞山虞医药有限公司'
    result = json.loads(
        (company_dir / 'qualification-submit-result.json').read_text(encoding='utf-8')
    )
    if (
        result.get('final_submission_success') is not False
        or str(result.get('error')) not in {
            '等待举证链接自动保存超时：豫械广审(文)第261112-17214号-样件表.jpg',
            '等待资质卡片自动保存超时：资质1',
            '等待资质“资质2”上传组件回填1个文件超时',
            '新增页存在非空补充资质草稿，拒绝自动覆盖',
            '找不到唯一可见的“新增补充资质”入口，匹配数：0',
            '业务“一类医疗器械”创建第1个资质卡片失败：未能创建第0个补充资质表单',
            '经营业务“二类医疗器械”的精确候选项被百度禁用，无法选择；请人工确认该公司适用的资质流程',
            '业务“电商代运营”第1个资质卡片数量异常：期望 1，实际 2',
        }
    ):
        raise RuntimeError('Submission result does not identify the known interrupted test draft')
    company = next(c for c in load_input(Path('input')) if c.company_name == '东莞山虞医药有限公司')
    config = BrowserConfig(auth_state_path=application_data_dir() / 'auth' / 'storage_state.json')
    with BrowserSession(config) as session:
        session.context.route('**/permit/web/permit/submitall', lambda route: route.abort())
        UploadCleaner(session, WorkflowConfig(final_submit=False, page_timeout_ms=60_000)).run_company(company)


if __name__ == '__main__':
    main()
