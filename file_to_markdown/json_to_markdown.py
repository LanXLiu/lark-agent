"""
JSON 数据转可读 Markdown。

按内容体量在「表格」与「标题层级」两种呈现间切换，依赖 ``json2markdown`` 与 ``tabulate``。
"""

import json
import json2markdown
from tabulate import tabulate
from typing import Union, List, Dict, Optional

class JsonToMarkdownConverter:
    """JSON 转 Markdown 转换器（支持一/二级标题 + 按字数智能切换表格/标题结构）"""
    
    def convert(
        self, 
        json_input, 
        title: str = "", 
        title_level: int = 1  # 新增：支持指定标题级别（1=一级，2=二级）
    ) -> str:
        """
        核心转换方法：支持一/二级标题 + 按字数智能切换表格/标题结构
        Args:
            json_input: 输入 JSON（字符串/字典/数组）
            title: 主标题文本（为空则用 JSON 顶级键作为标题）
            title_level: 主标题级别（1=一级#，2=二级##），默认1
        """
        # 校验标题级别
        if title_level not in [1, 2]:
            raise ValueError("title_level 仅支持 1（一级标题）或 2（二级标题）")
        
        # 1. 解析 JSON 输入
        json_data = self._parse_json(json_input)
        
        # 2. 统计内容总字数（决定转表格还是标题结构）
        total_chars = self._count_total_chars(json_data)
        
        # 3. 生成主标题（用指定级别）
        md_content = self._generate_title(title or self._get_default_title(json_data), title_level)
        
        # 4. 按字数智能转换
        if total_chars < 30:
            # 少于30字 → 转表格（字典/数组均支持）
            md_content += self._convert_to_table(json_data)
        else:
            # 30字及以上 → 转标题结构（主标题级别+嵌套子字段下一级标题）
            md_content += self._convert_to_title_structure(json_data, base_level=title_level)
        
        return md_content.strip()
    
    def _parse_json(self, json_input):
        """内部方法：解析 JSON 输入（兼容字符串/字典/数组）"""
        if isinstance(json_input, str):
            try:
                return json.loads(json_input)
            except json.JSONDecodeError as e:
                raise ValueError(f"JSON 解析失败：{str(e)}") from e
        elif isinstance(json_input, (dict, list)):
            return json_input
        else:
            raise ValueError("输入必须是 JSON 字符串、Python 字典或数组")
    
    def _generate_title(self, title: str, title_level: int) -> str:
        """内部方法：生成指定级别的 Markdown 标题"""
        if not title.strip():
            return ""
        return f"{'#' * title_level} {title.strip()}\n\n"
    
    def _get_default_title(self, json_data) -> str:
        """内部方法：获取默认标题（JSON 顶级键/数组描述）"""
        if isinstance(json_data, dict) and json_data:
            return list(json_data.keys())[0]  # 取第一个键作为默认标题
        elif isinstance(json_data, list) and json_data:
            return "数据列表"
        return "数据详情"
    
    def _count_total_chars(self, json_data) -> int:
        """内部方法：递归统计 JSON 所有内容的总字符数"""
        total = 0
        if isinstance(json_data, str):
            total += len(json_data.strip())
        elif isinstance(json_data, list):
            for item in json_data:
                total += self._count_total_chars(item)
        elif isinstance(json_data, dict):
            for value in json_data.values():
                total += self._count_total_chars(value)
        # 数字、布尔值转字符串统计
        elif isinstance(json_data, (int, float, bool)):
            total += len(str(json_data))
        return total
    
    def _process_cell_content(self, content) -> str:
        """辅助方法：处理内容（分点、换行、分段）"""
        if not content:
            return ""
        
        if isinstance(content, list):
            if content and isinstance(content[0], dict):
                sub_list = []
                for item in content:
                    for k, v in item.items():
                        sub_list.append(f"- **{k}**：{self._process_cell_content(v)}")
                return "\n".join(sub_list)
            else:
                return "\n- " + "\n- ".join([str(item) for item in content])
        
        if isinstance(content, dict):
            dict_str = []
            for k, v in content.items():
                dict_str.append(f"**{k}**：{self._process_cell_content(v)}")
            return "\n\n".join(dict_str)
        
        content_str = str(content)
        content_str = content_str.replace("\n\n", "\n").replace("\n", "<br>")
        if len(content_str) > 150:
            for sep in ["。", ".", "，", ","]:
                if sep in content_str:
                    content_str = content_str.replace(sep, sep + "<br>")
                    break
        return content_str
    
    def _convert_to_table(self, json_data) -> str:
        """优化表格生成：支持字典（单行列）和数组对象（多行列）"""
        processed_data = []
        
        # 字典 → 单行列表格（键=列名，值=内容）
        if isinstance(json_data, dict):
            if json_data:
                processed_item = {k: self._process_cell_content(v) for k, v in json_data.items()}
                processed_data.append(processed_item)
        # 数组 → 多行列表格（数组对象/普通数组）
        elif isinstance(json_data, list):
            if json_data and isinstance(json_data[0], dict):
                # 数组对象 → 多行多列
                for item in json_data:
                    processed_item = {k: self._process_cell_content(v) for k, v in item.items()}
                    processed_data.append(processed_item)
            else:
                # 普通数组 → 单列表格
                processed_data = [{"内容": self._process_cell_content(item)} for item in json_data]
        
        if not processed_data:
            return "| 无数据 |\n| --- |"
        
        headers = processed_data[0].keys()
        return tabulate(
            processed_data,
            headers="keys",
            tablefmt="pipe",
            colalign=["left"] * len(headers),
            missingval="",
            disable_numparse=True
        )
    
    def _convert_to_title_structure(self, json_data, base_level: int) -> str:
        """将 JSON 转为标题结构：主标题为 base_level，子字段转下一级标题（base_level+1）"""
        md = ""
        next_level = base_level + 1  # 子字段标题级别（主1→子2，主2→子3）
        
        if isinstance(json_data, dict):
            for key, value in json_data.items():
                # 子字段标题（下一级别）
                md += f"{'#' * next_level} {key}\n\n"
                # 递归处理子内容
                if isinstance(value, (dict, list)) and self._count_total_chars(value) > 20:
                    md += self._convert_to_title_structure(value, next_level)
                else:
                    md += self._process_cell_content(value) + "\n\n"
        
        elif isinstance(json_data, list):
            for idx, item in enumerate(json_data, 1):
                # 列表项标题（下一级别，带序号）
                md += f"{'#' * next_level} 第{idx}项\n\n"
                if isinstance(item, (dict, list)) and self._count_total_chars(item) > 20:
                    md += self._convert_to_title_structure(item, next_level)
                else:
                    md += self._process_cell_content(item) + "\n\n"
        
        return md.strip() + "\n"

# 测试代码
if __name__ == "__main__":
    # 测试1：字数<30字 → 转表格（字典输入）
    print("【测试1】字数<30字 → 表格")
    test_json1 = {"姓名": "张三", "年龄": 25, "职业": "工程师"}
    converter = JsonToMarkdownConverter()
    md1 = converter.convert(test_json1, title="个人信息", title_level=1)
    print(md1 + "\n\n" + "-"*80 + "\n")
    
    # 测试2：字数≥30字 → 转标题结构（嵌套字典，指定二级主标题）
    test_json2 =  {        "项目经历": [
            {
                "项目名称": "宠物用品售后小助手",
                "开始时间": "2024.10",
                "结束时间": "2025.3",
                "角色": "",
                "经历描述": "随着宠物用品市场快速发展，用户对售后服务的响应速度和专业性需求日益提升。传统客服系统存在响应延\n\n迟、标准不统一、专业知识覆盖不足等问题。本项目通过构建基于大语言模型（LLM）和检索增强生成（RAG（检索增强生成））技术的\n\n智能助手，结合多层级知识库（售后政策库、产品知识库、用户案例库），实现自动化售后咨询处理，覆盖退换货规则\n\n解读、产品使用指导、质量投诉受理等场景，显著提升服务效率与用户满意度。"
            },
            {
                "项目名称": "葡萄病害智能检测系统",
                "开始时间": "2024.2",
                "结束时间": "2024.9",
                "角色": "",
                "经历描述": "葡萄作为一种经济价值极高的水果被广泛种植，但生长过程中极易受到病害的侵袭。传统的病害检测\n\n方法主要依赖人工观察和经验判断，这种方式不仅效率低下，而且容易受到主观因素的影响，导致误判或漏判。\n\n本项目基于YOLOv8的图像识别技术，设计并实现一套葡萄病害智能检测系统。该系统能够通过对葡萄叶片的图\n\n像进行分析，快速、准确地识别出病害类型，帮助农户及时采取防治措施，有效控制病害的扩散，从而提升葡萄\n\n栽培的质量和产量，推动农业生产的智能化和可持续发展。\n\n项目方案:\n\n1. 模型设计与实现:设计并实现基于YOLOv8算法的葡萄病害智能检测模型，完成数据预处理、模型训练和参数调\n\n优。\n\n2. 数据处理与标注:对于葡萄病害位置进行标注，生成目标真值框。通过数据增强，将原始图片裁剪成不同尺寸，\n\n提高数据的多样性和模型的鲁棒性。\n\n3. 模型训练与优化：使用YOLOv8算法进行模型训练，结合CBAM通道注意力机制，提升模型的检测度。调整超\n\n参数(如学习率、批量大小等)和优化算法(如Adam和LAMB)，提升模型的训练效果和性能稳定性。\n\n4. 系统部署：使用瑞芯微的RK3588部署模型，利用NPU（神经网络处理单元）加速推理，实现实时病害检测，将YOLOv8模型转换为\n\nONNX格式，降低计算资源需求，提升推理速度。\n\n项目职责:\n\n1. 清洗制作数据集，标注病害位置。\n\n2. 根据客户需求训练优化模型、打包模型并编写项目效果表格。\n\n3. 协同部署工程师完成部署。\n\n项目成果:成功实现葡萄病害的高精度检测，显著降低了误检率和漏检率，提高葡萄栽培的质量和产量，帮助农户\n\n及时采取措施，有效控制病害扩散"
            },
            {
                "项目名称": "智能零售商店结算系统",
                "开始时间": "2023.5",
                "结束时间": "2024.1",
                "角色": "",
                "经历描述": "随着零售行业的快速发展和消费者对购物体验要求的不断提高，传统的超市结算方式已经难以满足现\n\n代消费者的需求。本项目旨在利用YOLO系列算法，设计并实现一套智能零售商店结算系统。该系统能够通过摄像\n\n头自动识别顾客购买的商品，并快速完成结算，无需人工干预。通过该系统，超市可以大幅提升结算效率，减少\n\n人力成本，同时为顾客提供更加便捷、高效的购物体验"
            },
            {
                "项目名称": "路边摊违规检测识别系统",
                "开始时间": "2022.9",
                "结束时间": "2023.4",
                "角色": "",
                "经历描述": "随而且成本高昂，难以实现全面、实时的监控。为了解决这一\n\n问题，本项目基于YOLOv5的"
            }
        ]}
    md2 = converter.convert(test_json2, title="项目经历", title_level=2)
    print("【测试2】字数≥30字 → 标题结构（二级主标题）")
    print(md2 + "\n\n" + "-"*80 + "\n")
    
    # 测试3：数组输入（字数<30）→ 表格
    test_json3 = [{"商品": "苹果", "价格": 5.9}, {"商品": "香蕉", "价格": 3.5}]
    md3 = converter.convert(test_json3, title="商品价格表", title_level=1)
    print("【测试3】数组输入（字数<30）→ 表格")
    print(md3)