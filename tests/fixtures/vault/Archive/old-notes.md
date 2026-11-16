---
title: "Archived Notes"
tags: [archive, old]
created: 2023-06-01
archived: true
---

# Archived Notes

Old notes kept for reference.

## Deprecated Patterns

Patterns no longer recommended.

### Legacy React Class Components

```jsx
class UserProfile extends React.Component {
  state = { user: null };

  componentDidMount() {
    fetchUser(this.props.userId).then(user => {
      this.setState({ user });
    });
  }

  render() {
    return <div>{this.state.user?.name}</div>;
  }
}
```

### Old Redux Patterns

```javascript
const ADD_TODO = 'ADD_TODO';

function todoReducer(state = [], action) {
  switch (action.type) {
    case ADD_TODO:
      return [...state, action.payload];
    default:
      return state;
  }
}
```

## Migrated Content

Content moved to new locations.

- Machine learning notes → Projects/machine-learning-notes.md
- Web development notes → Projects/web-development.md