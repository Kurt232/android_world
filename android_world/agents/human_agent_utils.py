import os
import yaml
import numpy as np

from PIL import Image
from typing import Any, Optional

from absl import logging

from android_world.env.representation_utils import UIElement, _accessibility_node_to_ui_element


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
  ele_id = 0

  for window in forest.windows:
    # each node has unique id in a window
    for node in window.tree.nodes:
      element: UIElement = _accessibility_node_to_ui_element(node, screen_size)
      ele_attr = EleAttr(ele_id, node.child_ids, element)
      id2element[ele_id] = ele_attr
      ele_attr.set_type('div')
      if not element.content_description and not element.text and not element.is_scrollable:
        ele_id += 1
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

      allowed_actions = ['click']
      status = []
      if element.is_editable:
        allowed_actions.append('input_text')
      if element.is_checkable:
        allowed_actions.extend(['select', 'unselect'])
        allowed_actions.remove('touch')
      if element.is_scrollable:
        allowed_actions.extend(['scroll up', 'scroll down'])
        allowed_actions.remove('click')
      if element.is_long_clickable:
        allowed_actions.append('long_press')
      if element.is_checked or element.is_selected:
        status.append('selected')

      ele_attr.action.extend(allowed_actions)
      ele_attr.status = status
      ele_attr.local_id = len(valid_ele_ids)

      id2element[ele_id] = ele_attr
      valid_ele_ids.append(ele_id)

      ele_id += 1

  element_tree = ElementTree(ele_attrs=id2element, valid_ele_ids=valid_ele_ids)

  return element_tree


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

  def __init__(self,
               idx: int,
               child_ids: list[int],
               ele: UIElement,
               use_class_name=True):
    '''
        @use_class_name: if True, use class name as the type of the element, otherwise use the <div>
        '''
    self.id = idx
    self.ele = ele
    self.children = child_ids

    self.resource_id = ele.resource_id
    self.class_name = ele.class_name
    self.text = ele.text
    self.content_description = ele.content_description
    self.bound_box = ele.bbox

    self.action = []
    # element representation
    self.local_id = None
    self.type = None
    self.alt = None
    self.status = None
    self.content = None

    self.type_ = self.class_name.split(
        '.')[-1] if self.class_name else 'div'  # only existing init

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


class ElementTree(object):

  def __init__(self, ele_attrs: dict, valid_ele_ids: list[int]):
    self.valid_ele_ids = set(valid_ele_ids)
    # tree
    self.ele_map: dict[int, EleAttr] = ele_attrs
    self.root = self._build_tree()
    # result
    self.str = self.get_str()

  def get_ele_by_id(self, index: int):
    return self.ele_map.get(index, None)

  class node(object):

    def __init__(self, nid: int, pid: int):
      self.children = []
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

  def _build_tree(self):
    root = self.node(0, -1)
    queue = [root]
    while queue:
      node = queue.pop(0)
      for child_id in self.ele_map[node.id].children:
        # some views are not in the enable views
        attr = self.ele_map.get(child_id, None)
        if not attr:
          continue
        idx = self.ele_map[child_id].id
        child = self.node(idx, node.id)
        node.children.append(child)
        queue.append(child)

    root.get_leaves()
    root.drop_invalid_nodes(self.valid_ele_ids)

    return root

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

  # def get_ele_by_xpath(self, xpath: str):
  #   html_view = self.str
  #   root = etree.fromstring(html_view)
  #   eles = root.xpath(xpath)
  #   if not eles:
  #     return None
  #   ele_desc = etree.tostring(eles[0], pretty_print=True).decode(
  #       'utf-8')  # only for father node
  #   id_str = re.search(r' id="(\d+)"', ele_desc).group(1)
  #   try:
  #     id = int(id_str)
  #   except Exception as e:
  #     print('fail to analyze xpath, err: {e}')
  #     raise e  # todo:: add a better way to handle this
  #   return self.eles[id]

  def get_children_by_ele(self, ele: EleAttr):
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

  def match_str_in_children(self, ele: EleAttr, key: str):
    eles = self.get_children_by_ele(ele)
    return [e for e in eles if e.is_match(key)]


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
      'height': height
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

  output_dir = os.path.join(save_path, 'views')
  if not os.path.exists(output_dir):
    os.makedirs(output_dir)
  file_path = os.path.join(output_dir, f"views_{tag}.jpg")
  image = Image.fromarray(pixels)
  image.save(file_path, format='JPEG')
