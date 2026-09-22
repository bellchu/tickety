const React = require('react');

function descendants(node, type) {
  if (!node || typeof node !== 'object') return [];
  return [...(node.type === type ? [node] : []), ...React.Children.toArray(node.props?.children).flatMap(child => descendants(child, type))];
}

module.exports = { descendants };
