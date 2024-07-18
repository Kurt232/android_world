# Copyright 2024 The android_world Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Utilities for agents."""

import ast
import os
import numpy as np
import json
import yaml
import re

from typing import Any, Optional

from lxml import etree
from PIL import Image
from absl import logging

from android_world.env.representation_utils import UIElement, _accessibility_node_to_ui_element


def extract_json(s: str) -> Optional[dict[str, Any]]:
  """Extracts JSON from string.

  Args:
    s: A string with a JSON in it. E.g., "{'hello': 'world'}" or from CoT:
      "let's think step-by-step, ..., {'hello': 'world'}".

  Returns:
    JSON object.
  """
  pattern = r'\{.*?\}'
  match = re.search(pattern, s)
  if match:
    try:
      return ast.literal_eval(match.group())
    except (SyntaxError, ValueError) as error:
      print('Cannot extract JSON, skipping due to error %s', error)
      return None
  else:
    return None


# HTML representation of the UI elements
def forest_to_element_tree(forest: Any,
                           screen_size: Optional[tuple[int, int]] = None):
  """Extracts nodes from accessibility forest and converts to UI elements.

  We extract all nodes that are either leaf nodes or have content descriptions
  or is scrollable.

  Args:
    forest: The forest to extract leaf nodes from.
    exclude_invisible_elements: True if invisible elements should not be
      returned.
    screen_size: The size of the device screen in pixels.

  Returns:
    The extracted UI elements.
  """

  logging.info('Converting forest to Ui Elements.')
  if screen_size is None:
    logging.warning('screen_size=None, no normalized bbox for elements.')

  id2element: dict[int, UIElement] = {}
  valid_ele_ids: list[int] = []
  if len(forest.windows) == 0:
    return ElementTree(ele_attrs=id2element, valid_ele_ids=valid_ele_ids)

  # only windows[0] is showing the main activity
  for node in forest.windows[0].tree.nodes:
    node_id: int = node.unique_id
    element: UIElement = _accessibility_node_to_ui_element(node, screen_size)
    ele_attr = EleAttr(node_id, node.child_ids, element)
    id2element[node_id] = ele_attr
    ele_attr.set_type('div')
    # TODO:: add the element type for image
    if (node.child_ids and not node.content_description and not node.is_scrollable) or not node.is_visible_to_user:
      continue

    text = element.text if element.text else ''
    text = text.replace('\n', ' \\ ')
    text = text[:50] if len(text) > 50 else text
    ele_attr.content = text
    ele_attr.alt = element.content_description
    if element.is_editable:
      ele_attr.set_type('input')
    elif element.is_checkable:
      ele_attr.set_type('checkbox')
    elif element.is_clickable or element.is_long_clickable:
      ele_attr.set_type('button')
    elif element.is_scrollable:
      ele_attr.set_type('scrollbar')
    else:
      ele_attr.set_type('p')

    allowed_actions = ['touch']
    allowed_actions_aw = ['click']
    status = []
    if element.is_editable:
      allowed_actions.append('set_text')
      allowed_actions_aw.append('input_text')
    if element.is_checkable:
      allowed_actions.extend(['select', 'unselect'])
      allowed_actions.remove('touch')
    if element.is_scrollable:
      allowed_actions.extend(['scroll up', 'scroll down'])
      allowed_actions.remove('touch')
      allowed_actions_aw.extend(['scroll'])
      allowed_actions_aw.remove('click')
    if element.is_long_clickable:
      allowed_actions.append('long_touch')
      allowed_actions_aw.append('long_press')
    if element.is_checked or element.is_selected:
      status.append('selected')

    ele_attr.action.extend(allowed_actions)
    ele_attr.action_aw.extend(allowed_actions_aw)

    ele_attr.status = status
    ele_attr.local_id = len(valid_ele_ids)

    valid_ele_ids.append(node_id)

  return ElementTree(ele_attrs=id2element, valid_ele_ids=valid_ele_ids)


def _escape_xml_chars(input_str: str):
  """
    Escapes special characters in a string for XML compatibility.

    Args:
        input_str (str): The input string to be escaped.

    Returns:
        str: The escaped string suitable for XML use.
    """
  if not input_str:
    return input_str
  return (input_str.replace("&", "&amp;").replace("<", "&lt;").replace(
      ">", "&gt;").replace('"', "&quot;").replace("'", "&apos;"))


class EleAttr(object):

  def __init__(self, idx: int, child_ids: list[int], ele: UIElement):
    '''
        @use_class_name: if True, use class name as the type of the element, otherwise use the <div>
        '''
    self.id = idx
    self.ele = ele
    self.children = child_ids

    self.resource_id = ele.resource_name
    self.class_name = ele.class_name
    self.text = ele.text
    self.content_description = ele.content_description
    self.bound_box = ele.bbox

    self.action = []
    self.action_aw = []
    # element representation
    self.local_id = None
    self.type = None
    self.alt = None
    self.status = None
    self.content = None

    self.type_ = self.class_name.split(
        '.')[-1] if self.class_name else 'div'  # only existing init

  # compatible with the old version
  @property
  def view_desc(self) -> str:
    return '<' + self.type + \
        (f' id={self.local_id}' if self.local_id else '') + \
        (f' alt=\'{self.alt}\'' if self.alt else '') + \
        (f' status={",".join(self.status)}' if self.status and len(self.status)>0 else '') + \
        (f' bound_box={self.bound_box}' if self.bound_box else '') + '>' + \
        (self.content if self.content else '') + \
        self.desc_end

  # compatible with the old version
  @property
  def full_desc(self) -> str:
    return '<' + self.type + \
        (f' alt=\'{self.alt}\'' if self.alt else '') + \
        (f' status={",".join(self.status)}' if self.status and len(self.status)>0 else '') + \
        (f' bound_box={self.bound_box}' if self.bound_box else '') + '>' + \
        (self.content if self.content else '') + \
        self.desc_end

  # compatible with the old version
  @property
  def desc(self) -> str:
    return '<' + self.type + \
        (f' alt=\'{self.alt}\'' if self.alt else '') + \
        (f' bound_box={self.bound_box}' if self.bound_box else '') + '>' + \
        (self.content if self.content else '') + \
        self.desc_end

  # compatible with the old version
  @property
  def desc_end(self) -> str:
    return f'</{self.type}>'

  # generate the html description
  @property
  def desc_html_start(self) -> str:
    # add double quote to resource_id and other properties
    if self.resource_id:
      resource_id = self.resource_id.split('/')[-1]
    else:
      resource_id = ''
    resource_id = _escape_xml_chars(resource_id)
    typ = _escape_xml_chars(self.type_)
    alt = _escape_xml_chars(self.alt)
    status = None if not self.status else [
        _escape_xml_chars(s) for s in self.status
    ]
    content = _escape_xml_chars(self.content)
    return '<' + typ + f' id=\'{self.id}\'' + \
        (f" resource_id='{resource_id}'" if resource_id else '') + \
        (f' alt=\'{alt}\'' if alt else '') + \
        (f' status=\'{",".join(status)}\'' if status and len(status)>0 else '') + '>' + \
        (content if content else '')

  # generate the html description
  @property
  def desc_html_end(self) -> str:
    return f'</{_escape_xml_chars(self.type_)}>'

  def set_type(self, typ: str):
    self.type = typ
    if typ in ['button', 'checkbox', 'input', 'scrollbar', 'p']:
      self.type_ = self.type

  def is_match(self, value: str):
    if value == self.alt:
      return True
    if value == self.content:
      return True
    if value == self.text:
      return True
    return False

  def check_action(self, action_type: str):
    return action_type in self.action_aw


class ElementTree(object):

  def __init__(self, ele_attrs: dict[int, EleAttr], valid_ele_ids: list[int]):
    # tree
    self.root, self.ele_map, self.valid_ele_ids = self._build_tree(
        ele_attrs, valid_ele_ids)
    self.size = len(self.ele_map)
    # result
    self.str = self.get_str()

  def get_ele_by_id(self, index: int):
    return self.ele_map.get(index, None)

  def __len__(self):
    return self.size

  class node(object):

    def __init__(self, nid: int, pid: int):
      self.children: list = []
      self.id = nid
      self.parent = pid
      self.leaves = set()

    def get_leaves(self):
      for child in self.children:
        if not child.children:
          self.leaves.add(child.id)
        else:
          self.leaves.update(child.get_leaves())

      return self.leaves

    def drop_invalid_nodes(self, valid_node_ids: set):
      in_set = self.leaves & valid_node_ids
      if in_set:
        self.leaves = in_set
        for child in self.children:
          child.drop_invalid_nodes(valid_node_ids)
      else:
        # drop
        self.children.clear()
        self.leaves.clear()

  def _build_tree(self, ele_map: dict[int, EleAttr], valid_ele_ids: list[int]):
    root = self.node(0, -1)
    queue = [root]
    while queue:
      node = queue.pop(0)
      for child_id in ele_map[node.id].children:
        # some views are not in the enable views
        attr = ele_map.get(child_id, None)
        if not attr:
          continue
        idx = ele_map[child_id].id
        child = self.node(idx, node.id)
        node.children.append(child)
        queue.append(child)

    # get dfs order
    dfs_order = []
    stack = [root]
    while stack:
      node = stack.pop()
      dfs_order.append(node)
      stack.extend(reversed(
          node.children))  # Reverse to maintain the original order in a DFS

    # convert bfs order id to dfs order id
    idx_map = {node.id: idx for idx, node in enumerate(dfs_order)}
    # update the ele_map
    _ele_map = {}
    for idx, node in enumerate(dfs_order):
      ele = ele_map[node.id]
      ele.id = idx
      for i, child in enumerate(ele.children):
        ele.children[i] = idx_map[child]
      _ele_map[idx] = ele
    # update the valid_ele_ids
    _valid_ele_ids = set([idx_map[idx] for idx in valid_ele_ids])
    # update the node
    for node in dfs_order:
      node.id = idx_map[node.id]
      if node.parent != -1:
        node.parent = idx_map.get(node.parent, -1)

    # get the leaves
    root.get_leaves()
    root.drop_invalid_nodes(_valid_ele_ids)

    return root, _ele_map, _valid_ele_ids

  def get_str(self, is_color=False) -> str:
    '''
        use to print the tree in terminal with color
        '''

    # output like the command of pstree to show all attribute of every node
    def _str(node, depth=0):
      attr = self.ele_map[node.id]
      end_color = '\033[0m'
      if attr.type != 'div':
        color = '\033[0;32m'
      else:
        color = '\033[0;30m'
      if not is_color:
        end_color = ''
        color = ''
      if len(node.children) == 0:
        return color + f'{"  "*depth}{attr.desc_html_start}{attr.desc_html_end}\n' + end_color
      ret = color + f'{"  "*depth}{attr.desc_html_start}\n' + end_color
      for child in node.children:
        ret += _str(child, depth + 1)
      ret += color + f'{"  "*depth}{attr.desc_html_end}\n' + end_color
      return ret

    return _str(self.root)

  def get_ele_by_xpath(self, xpath: str) -> None | EleAttr:
    html_view = self.str
    root = etree.fromstring(html_view)
    eles = root.xpath(xpath)
    if not eles:
      return None
    ele_desc = etree.tostring(eles[0], pretty_print=True).decode(
        'utf-8')  # only for father node
    id_str = re.search(r' id="(\d+)"', ele_desc).group(1)
    try:
      id = int(id_str)
    except Exception as e:
      print('fail to analyze xpath, err: {e}')
      raise e  # todo:: add a better way to handle this
    print('found element with id', id)
    return self.ele_map[id]

  def match_str_in_children(self, ele: EleAttr, key: str):
    eles = self.get_children_by_ele(ele)
    return [e for e in eles if e.is_match(key)]

  def get_children_by_ele(self, ele: EleAttr) -> list[EleAttr]:
    if ele.id not in self.ele_map:
      return []
    que = [self.root]
    target = None
    while len(que) > 0:
      node = que.pop(0)
      if node.id == ele.id:
        target = node
        break
      for child in node.children:
        que.append(child)
    if target == None:
      return []
    # only for valid children, the sort is ascending order of the id
    return [self.ele_map[idx] for idx in sorted(target.leaves)]

  def get_children_by_idx(self, ele: EleAttr, idx: int):
    for childid, child in enumerate(ele.children):
      if childid == idx:
        return self.ele_map[child]
    return None

  def match_str_in_children(self, ele: EleAttr, key: str):
    eles = self.get_children_by_ele(ele)
    return [e for e in eles if e.is_match(key)]

  def get_ele_text(self, ele):
    if ele.text:
      return ele.text
    for child in ele.children:
      child_text = self.get_ele_text(self.ele_map[child])
      if child_text is not None:
        return child_text
    return None

  def get_content_desc(self, ele):
    if ele.content_description:
      return ele.content_description
    for child in ele.children:
      child_content = self.get_content_desc(self.ele_map[child])
      if child_content is not None:
        return child_content
    return None

  def get_text(self, ele):
    ele_text = self.get_ele_text(ele)
    if ele_text:
      return ele_text
    ele_content_description = self.get_content_desc(ele)
    if ele_content_description:
      return ele_content_description

  def get_all_children_by_ele(self, ele: EleAttr):
    try:
      result = [self.ele_map[child] for child in ele.children]
    except:
      import pdb
      pdb.set_trace()
    if not result:
      return []
    for child in ele.children:
      result.extend(self.get_all_children_by_ele(self.ele_map[child]))
    return result

  def get_ele_descs_without_text(self):
    ele_descs = []
    for ele_id, ele in self.ele_map.items():
      ele_dict = ele.dict()
      ele_desc = ''
      for k in [
          'resource_id', 'class_name', 'content_description', 'bound_box'
      ]:
        if ele_dict[k]:
          ele_desc += f'{k}={ele_dict[k]} '
      ele_descs.append(ele_desc)
    return ele_descs

  def get_ele_id_by_properties(self, key_values: dict):
    for ele_id, ele in self.ele_map.items():
      ele_dict = ele.dict()
      matched = True
      for k, v in key_values.items():
        if k not in ele_dict.keys() or ele_dict[k] != v:
          matched = False
          break
      if matched:
        return ele.id
    return -1


def save_to_yaml(save_path: str, html_view: str, tag: str, action_type: str,
                 action_details: dict, choice: int | None, input_text: str,
                 width: int, height: int):
  if not save_path:
    return

  file_name = os.path.join(save_path, 'log.yaml')

  if not os.path.exists(file_name):
    tmp_data = {'step_num': 0, 'records': []}
    with open(file_name, 'w', encoding='utf-8') as f:
      yaml.dump(tmp_data, f)

  with open(file_name, 'r', encoding='utf-8') as f:
    old_yaml_data = yaml.safe_load(f)
  new_records = old_yaml_data['records']
  new_records.append({
      'State': html_view,
      'Action': action_type,
      'ActionDetails': action_details,
      'Choice': choice,
      'Input': input_text,
      'tag': tag,
      'width': width,
      'height': height,
      'dynamic_ids': []
  })
  data = {
      'step_num': len(list(old_yaml_data['records'])),
      'records': new_records
  }
  with open(file_name, 'w', encoding='utf-8') as f:
    yaml.dump(data, f)


def save_screenshot(save_path: str, tag: str, pixels: np.ndarray):
  if not save_path:
    return

  output_dir = os.path.join(save_path, 'states')
  if not os.path.exists(output_dir):
    os.makedirs(output_dir)
  file_path = os.path.join(output_dir, f"screen_{tag}.png")
  image = Image.fromarray(pixels)
  image.save(file_path, 'PNG')


def save_raw_state(save_path: str, tag: str, forest: Any):
  if not save_path:
    return

  output_dir = os.path.join(save_path, 'states')
  if not os.path.exists(output_dir):
    os.makedirs(output_dir)
  file_path = os.path.join(output_dir, f"state_{tag}.json")
  if len(forest.windows) == 0:
    return
  state = []
  # only windows[0] is showing the main activity
  for node in forest.windows[0].tree.nodes:
    element = _accessibility_node_to_ui_element(node, None)
    state.append({
        'id': int(node.unique_id),
        'child_ids': [idx for idx in node.child_ids],
        'text': element.text,
        'content_description': element.content_description,
        'class_name': element.class_name,
        'bound_box': [[element.bbox_pixels.x_min, element.bbox_pixels.y_min],
                      [element.bbox_pixels.x_max, element.bbox_pixels.y_max]],
        'is_checked': element.is_checked,
        'is_checkable': element.is_checkable,
        'is_clickable': element.is_clickable,
        'is_editable': element.is_editable,
        'is_enabled': element.is_enabled,
        'is_focused': element.is_focused,
        'is_focusable': element.is_focusable,
        'is_long_clickable': element.is_long_clickable,
        'is_scrollable': element.is_scrollable,
        'is_selected': element.is_selected,
        'is_visible': element.is_visible,
        'package_name': element.package_name,
        'resource_id': element.resource_name
    })

  json.dump(state, open(file_path, 'w'), indent=2)
